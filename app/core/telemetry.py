"""
链路追踪（OpenTelemetry）
=========================
把一次对话拆成可读的 span 树，回答「这轮为什么慢 / 为什么答错」：

    POST /chat/stream                        ← FastAPI 自动埋点
    └── agent.turn                           ← 一轮完整对话
        ├── context.build                    ← 系统提示组装
        │   ├── rag.retrieve                 ← 知识库检索
        │   └── memory.search                ← 长期记忆检索
        ├── chat glm-4.5-flash               ← LLM 调用（gen_ai.* 属性）
        ├── execute_tool get_weather         ← 工具执行（每个 tool_call 一条）
        └── chat glm-4.5-flash               ← 工具结果回填后的第二次 LLM

为什么值得做：这次修掉的「每轮调两次 LLM」如果当初有 span 树，
一个 turn 里出现两条 chat span 一眼就能看见，不必靠人读代码发现。

设计约束：
1. **禁用时零开销**——不配置 TracerProvider 时，OTel API 返回 no-op tracer，
   start_span 几乎不产生成本，所以业务代码里可以无条件打点，不用到处写 if。
2. **不破坏流式**——FastAPI 埋点是纯 ASGI 层的，与项目已有的
   RateLimit/Metrics 中间件同层，不会缓冲 SSE。
3. **默认不记录正文**——prompt/completion 可能含用户隐私与密钥，
   只有显式打开 OTEL_CAPTURE_CONTENT 才作为 span 事件记录。

遵循 OpenTelemetry GenAI 语义约定（gen_ai.*），可直接对接 Jaeger /
Grafana Tempo / 任意 OTLP 后端，不绑定特定厂商。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, StatusCode

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# GenAI 语义约定属性名
# ---------------------------------------------------------------------------
# 直接用字符串常量而不是 import opentelemetry.semconv._incubating：
# GenAI 约定还在 incubating 阶段，模块路径几个版本就会挪一次，
# 而属性名本身是稳定的（规范里已冻结）。
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"

# 本项目自定义属性统一加 selfagent. 前缀，与标准属性区分开
ATTR_THREAD_ID = "selfagent.thread_id"
ATTR_TENANT_ID = "selfagent.tenant_id"
ATTR_USER_ID = "selfagent.user_id"
ATTR_STREAMING = "selfagent.streaming"
ATTR_MESSAGE_COUNT = "selfagent.message_count"
ATTR_TOOL_CALL_COUNT = "selfagent.tool_call_count"
ATTR_TOOL_RESULT_CHARS = "selfagent.tool.result_chars"
ATTR_TOOL_TRUNCATED = "selfagent.tool.truncated"
ATTR_KB_IDS = "selfagent.kb_ids"
ATTR_CHUNK_COUNT = "selfagent.chunk_count"
ATTR_MEMORY_HITS = "selfagent.memory_hits"
ATTR_COMPRESSED = "selfagent.context_compressed"

_TRACER_NAME = "self-agent"
_initialized = False


def get_tracer() -> trace.Tracer:
    """获取 tracer。未初始化时返回 no-op，调用方无需判空。"""
    return trace.get_tracer(_TRACER_NAME)


def setup_telemetry(app: Any = None) -> bool:
    """初始化链路追踪。返回是否真的启用了。

    OTEL_ENABLED=false（默认）时直接返回，不注册任何 provider——
    此时全局仍是 OTel 的 no-op 实现，业务代码里的 start_span 近乎免费。
    """
    global _initialized
    if _initialized:
        return True

    s = get_settings()
    if not s.otel_enabled:
        logger.info("链路追踪未启用（OTEL_ENABLED=false）")
        return False

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError as e:
        logger.warning("opentelemetry-sdk 未安装，链路追踪不可用：%s", e)
        return False

    resource = Resource.create({
        "service.name": s.otel_service_name,
        "service.version": s.app_version,
        "deployment.environment.name": s.app_env,
    })
    provider = TracerProvider(resource=resource)

    exported = False
    if s.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            endpoint = s.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            logger.info("链路追踪：OTLP → %s", endpoint)
            exported = True
        except Exception as e:  # noqa: BLE001
            logger.warning("OTLP exporter 初始化失败：%s", e)

    if s.otel_console_export or not exported:
        # 没有配 OTLP 后端时退到控制台，至少能看见 span 结构
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        if not exported:
            logger.info("链路追踪：未配置 OTLP 后端，span 输出到控制台")

    trace.set_tracer_provider(provider)

    # HTTP 层自动埋点（纯 ASGI，不缓冲流式响应）
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=provider,
                # 健康检查和指标会被探针高频打，排除掉免得淹没有效 span
                excluded_urls="health,metrics",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("FastAPI 自动埋点失败：%s", e)

    # 出站 HTTP 自动埋点，便于看到外部依赖耗时（状态码、429 重试都是独立 span）。
    # 进程里有两套 HTTP 栈，必须两个都挂：
    #   httpx  → A2A 客户端、langsmith
    #   httpx2 → openai 3.x / anthropic 1.x / mcp 2.x 的默认客户端（LLM 请求走这条）
    # 只挂 httpx 的话，LLM 请求只剩手写的 `chat {model}` span，看不到底下的 HTTP 重试。
    # HTTPX2ClientInstrumentor 自 opentelemetry-instrumentation-httpx 0.66b 起提供。
    for label, cls_name in (("httpx", "HTTPXClientInstrumentor"), ("httpx2", "HTTPX2ClientInstrumentor")):
        try:
            from opentelemetry.instrumentation import httpx as otel_httpx

            getattr(otel_httpx, cls_name)().instrument(tracer_provider=provider)
            logger.info("✅ %s 出站请求自动埋点已启用", label)
        except Exception as e:  # noqa: BLE001
            logger.warning("%s 自动埋点失败（不影响主流程，但该栈的出站请求不会有 HTTP span）：%s", label, e)

    _initialized = True
    logger.info("✅ 链路追踪已启用（service=%s）", s.otel_service_name)
    return True


def shutdown_telemetry() -> None:
    """关闭时 flush 未导出的 span，避免丢最后一批。"""
    global _initialized
    if not _initialized:
        return
    try:
        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if shutdown:
            shutdown()
    except Exception as e:  # noqa: BLE001
        logger.warning("链路追踪关闭失败：%s", e)
    _initialized = False


def current_trace_id() -> str | None:
    """当前活动 span 的 trace_id（32 位十六进制）。无活动 span 返回 None。

    日志模块用它把日志和 span 串起来：同一个 trace_id 既能在日志里 grep，
    也能在 Jaeger 里直接搜到对应的调用树。
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def record_content(span: Span, key: str, content: str) -> None:
    """按需记录 prompt/completion 正文（默认关闭）。

    正文可能含用户隐私、密钥、内部文档内容，不能默认往 trace 后端送。
    只有显式打开 OTEL_CAPTURE_CONTENT 才记录，且截断防止 span 过大。
    """
    if not get_settings().otel_capture_content:
        return
    span.add_event(key, {"content": content[:2000]})


@contextmanager
def llm_span(
    *,
    provider: str,
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    message_count: int = 0,
    streaming: bool = True,
):
    """LLM 调用 span。命名遵循 GenAI 约定：`chat {model}`。"""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as span:
        span.set_attribute(GEN_AI_SYSTEM, provider)
        span.set_attribute(GEN_AI_OPERATION_NAME, "chat")
        span.set_attribute(GEN_AI_REQUEST_MODEL, model)
        span.set_attribute(ATTR_MESSAGE_COUNT, message_count)
        span.set_attribute(ATTR_STREAMING, streaming)
        if temperature is not None:
            span.set_attribute(GEN_AI_REQUEST_TEMPERATURE, temperature)
        if max_tokens is not None:
            span.set_attribute(GEN_AI_REQUEST_MAX_TOKENS, max_tokens)
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            raise


def finish_llm_span(
    span: Span,
    *,
    usage: Any = None,
    model: str = "",
    finish_reason: str | None = None,
    tool_call_count: int = 0,
) -> None:
    """给 LLM span 补上响应侧属性（token 用量等）。"""
    if model:
        span.set_attribute(GEN_AI_RESPONSE_MODEL, model)
    if finish_reason:
        span.set_attribute(GEN_AI_RESPONSE_FINISH_REASONS, [finish_reason])
    span.set_attribute(ATTR_TOOL_CALL_COUNT, tool_call_count)
    if usage is not None:
        span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, getattr(usage, "prompt_tokens", 0) or 0)
        span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, getattr(usage, "completion_tokens", 0) or 0)


@contextmanager
def tool_span(*, name: str, call_id: str = ""):
    """工具执行 span。命名遵循 GenAI 约定：`execute_tool {name}`。"""
    tracer = get_tracer()
    with tracer.start_as_current_span(f"execute_tool {name}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute(GEN_AI_TOOL_NAME, name)
        span.set_attribute(GEN_AI_OPERATION_NAME, "execute_tool")
        if call_id:
            span.set_attribute(GEN_AI_TOOL_CALL_ID, call_id)
        yield span


@contextmanager
def span(name: str, **attributes: Any):
    """通用内部 span（RAG 检索、记忆检索、上下文压缩等）。"""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as sp:
        for k, v in attributes.items():
            if v is not None:
                sp.set_attribute(k, v)
        try:
            yield sp
        except Exception as e:
            sp.record_exception(e)
            sp.set_status(StatusCode.ERROR, str(e))
            raise
