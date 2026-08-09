# 第 1 章：多模态 API 怎么传图（GLM-4.5V / OpenAI / Anthropic）

> 这章讲透三家怎么传图。**好消息：GLM-4.5V 走 OpenAI 兼容协议**，所以 Self-Agent 接它几乎不用改 provider，主要改数据模型。

---

## 1.1 核心变化：content 从"字符串"变"块数组"

纯文本时代，一条消息的 content 是字符串：
```json
{"role": "user", "content": "你好"}
```

多模态时代，content 变成**块数组**（content blocks），每块有 type：
```json
{"role": "user", "content": [
    {"type": "text", "text": "图中是什么？"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
]}
```

**这就是多模态的本质**：一条消息可以同时包含文本块和图片块（甚至视频块）。

---

## 1.2 GLM-4.5V（Self-Agent 默认 provider 的视觉版）

### 模型信息
- **模型名**：`glm-4.5v`
- **架构**：MoE，总参 106B、激活 12B
- **能力**：图像、视频、文档理解、GUI 任务

### 接口格式（OpenAI 兼容，已核实）

走的就是 Self-Agent 已经在用的 `https://open.bigmodel.cn/api/paas/v4/chat/completions`，只是 `model` 换成 `glm-4.5v`，content 用数组：

```json
{
  "model": "glm-4.5v",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "请描述这张图"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ..."}}
    ]
  }]
}
```

### 图片两种传法

1. **base64 data URL**：`data:image/jpeg;base64,{base64字符串}`
2. **http/https URL**：直接传图片的公网 URL（无需 base64）

### 关键点（对 Self-Agent 改造的影响）

**几乎不用改 provider**——`OpenAILikeClient` 已经用 openai SDK，SDK 原生支持 content blocks。**只需要把 `ChatMessage.content` 从纯 str 扩展成支持 content blocks**，provider 自动透传。

---

## 1.3 OpenAI（GPT-4V / GPT-4o）

格式和 GLM-4.5V 几乎一样（GLM 兼容 OpenAI）：

```json
{"type": "image_url", "image_url": {"url": "..."}}
```

也支持 base64 data URL 和 http URL。

### `detail` 参数（OpenAI 独有）

OpenAI 的 image_url 块可带 `detail`：
- `low`：固定费用，512×512
- `high`：按缩放层级收费，更清晰
- `auto`（默认）：模型决定

GLM-4.5V 不一定支持这个参数（待核实），但传了会忽略。

---

## 1.4 Anthropic（Claude）

Claude 的图片格式**略有不同**，不在 image_url 里，而是 `image` 块：

```json
{"type": "image", "source": {
    "type": "base64",
    "media_type": "image/jpeg",
    "data": "base64字符串（不含 data: 前缀）"
}}
```

注意：
- Anthropic 的 base64 **不含 `data:image/...;base64,` 前缀**，只要纯 base64
- `media_type` 单独指定（image/jpeg、image/png、image/gif、image/webp）
- 也支持 URL source（`"type": "url", "url": "..."`）

**对 Self-Agent 的影响**：`anthropic.py` 的 `_to_anthropic_messages` 要单独处理图片块（格式不同），`openai_like.py` 可以直接透传。

---

## 1.5 三家对比

| 维度 | GLM-4.5V / OpenAI | Anthropic |
|---|---|---|
| 图片块 type | `image_url` | `image` |
| base64 格式 | `data:image/jpeg;base64,...`（含前缀） | 纯 base64（不含前缀）+ media_type |
| URL 支持 | ✅ | ✅（较新版本） |
| detail 参数 | OpenAI 有 / GLM 待核实 | 无 |

**关键**：provider 层要分别处理，但数据模型层可以统一抽象成"content blocks"。

---

## 1.6 多图、视频

### 多图

content 数组里放多个 image 块即可：
```json
"content": [
    {"type": "text", "text": "比较这两张图"},
    {"type": "image_url", "image_url": {"url": "图1"}},
    {"type": "image_url", "image_url": {"url": "图2"}}
]
```

### 视频

GLM-4.5V 支持视频（抽帧）。格式上通常是传视频 URL，模型内部抽帧处理。具体格式以官方文档为准（待核实最新接口）。

---

## 1.7 面试要点

> **Q：多模态 LLM 的图片是怎么传的？**
> A：content 从字符串变成"块数组"，每个块有 type（text/image_url）。图片用 base64 data URL 或 http URL 传。GLM-4.5V/OpenAI 用 image_url 块，Anthropic 用 image 块且 base64 不含前缀。

> **Q：base64 传图有什么问题？**
> A：① 体积膨胀约 33%（3 字节变 4 字符）；② 大图撑爆请求体；③ 编解码开销。所以也有 URL 直传方案（图片要先能公网访问）。

→ [下一章：Self-Agent 改造方案](02-改造方案.md)
