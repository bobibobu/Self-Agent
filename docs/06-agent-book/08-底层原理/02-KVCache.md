# 第 2 章：KV Cache、Prefill vs Decode、Prompt Caching 的原理

> 这章把"你做的 prompt caching 改造"讲透到原理层——为什么前缀改一个 token 整条失效、为什么 prefill 慢 decode 快、KV Cache 到底缓存了什么。
>
> 这是面试深水区：能答到这层，证明你不只是"会用"，而是"懂为什么"。

---

## 2.1 KV Cache 到底缓存了什么

**答：缓存的是 Transformer 每一层、每个注意力头，对每个 token 算出的 Key 和 Value 向量。**

### 为什么需要缓存

Attention 里，每个新 token 要"看"前面所有 token。具体说，算第 t 个 token 的输出，需要它的 Q 和**所有前序 token 的 K、V**。

如果不缓存：每生成一个 token，都要重算前面所有 token 的 K/V——复杂度 O(n²)，n 是序列长度，生成 n 个 token 就是 O(n³)。

如果缓存：前面 token 的 K/V 算一次存下来，生成新 token 时只算新 token 的 K/V，追加进 cache。

### 缓存的形状

`(层数, 头数, seq_len, head_dim)`。比如 32 层、32 头、head_dim=128、seq_len=4096，KV cache 就是 `(32, 32, 4096, 128)` 两个张量（K 和 V）。这就是为什么长上下文吃显存。

---

## 2.2 为什么前缀改一个 token，整条缓存失效

**这是 prompt caching 的核心铁律，必须答到原理。**

KV cache 是**按 token 位置存的**。第 i 个位置的 K/V 依赖**第 0 到 i 所有 token**（因为 Attention 是对前面所有 token 加权求和）。

所以：
- 如果第 0 个 token（最前面的系统提示）改了 → 它的 K/V 变 → 第 1 个 token 的 attention 输出变（因为它看第 0 个）→ 第 1 个的 K/V 变 → 第 2 个的 attention 输出变 → ... → **雪崩式全部失效**
- 如果只改最后面的 token → 前面的 K/V 不变 → **前面都能命中，只有最后重算**

**这就是为什么"固定前缀"是缓存命中的关键**：前缀固定，前面所有 token 的 KV 都能复用；动态内容放末尾，只影响末尾少量 token 的 KV。

### 和你的改造连起来

你的 prompt caching 改造：把时间戳从 SYSTEM_PROMPT 开头移到对话末尾。原理上就是——
- 改造前：时间戳在最前面，每轮变 → 第一个 token 的 KV 变 → 雪崩，整条 cache 失效
- 改造后：时间戳在最后面 → 前面所有 token（SYSTEM_PROMPT 主体）的 KV 不变 → **前面全部命中，只有末尾时间戳那几个 token 重算**

**这一答，把"懂 KV Cache 原理"和"有实战改造经验"同时证明了。**

---

## 2.3 Prefill vs Decode：为什么首字慢、后面快

（豆包一面重点）

### 两个阶段

LLM 推理分两阶段：

| 阶段 | 做什么 | 计算特性 | 速度 |
|---|---|---|---|
| **Prefill（预填充）** | 处理整个 prompt，算出所有 token 的 KV cache | **计算密集**（矩阵乘法多，算力打满） | 慢 |
| **Decode（解码）** | 逐个生成 token，每次只算一个新 token 的 Q（K/V 追加进 cache） | **访存密集**（算得少，但要频繁读写 KV cache，受显存带宽限制） | 快（单个 token 快，但要生成很多个） |

### 为什么 prefill 慢

Prefill 要处理整个 prompt（可能几千 token），算它们的 QK^T——这是个 `(seq_len, seq_len)` 的大矩阵乘法，计算量大但能并行，算力打满。延迟取决于 prompt 长度。

### 为什么 decode 单 token 快但整体慢

Decode 每次只算一个新 token（1 个 Q × 所有 K），计算量小。但每生成一个 token 都要读整个 KV cache（访存），**算力利用率低，瓶颈在显存带宽**。所以单个 token 快，但生成 1000 个 token 要串行 1000 次，总时间不短。

### 对 Agent 首字延迟的影响

Agent 的"首字延迟"= context.build（检索/记忆）+ **prefill**（处理 system + history）+ 第一个 decode token。

你的项目里（[书1第 12 章](../01-全书/12-完整链路拆解.md) 的 trace），`chat glm-4.5-flash 820ms` 主要是 prefill（处理 system prompt + history）。**prompt caching 命中后，prefill 阶段前缀部分复用 KV，首字延迟显著降低。**

---

## 2.4 Prompt Caching 各家政策（回顾第 6 本书第 3 章）

| 厂商 | 启用 | 命中折扣 | 原理差异 |
|---|---|---|---|
| Anthropic | 手动 cache_control | 省 90% | 显式标 breakpoint，按 block 缓存 KV |
| OpenAI | 全自动 | 省 50% | 隐式检测前缀匹配，命中免 prefill |
| DeepSeek | 全自动 | 省 90% | 64-token chunk 粒度缓存 |
| GLM | 隐式自动 | 省 50-80% | 自动识别重复上下文 |

**本质都是一样的**：前缀匹配的 KV 张量复用，跳过那部分 prefill 计算。差别只在"怎么标记、粒度多细"。

---

## 2.5 GQA / MQA：减少 KV cache 显存

（面试常问"常见推理优化"时展开）

KV cache 占显存大（长上下文尤其）。**GQA（Grouped-Query Attention）/ MQA（Multi-Query Attention）** 通过减少 KV 的头数来降显存：

- **标准 MHA**：Q 有 H 个头，K/V 也有 H 个头 → KV cache = `(H, seq, dim)`
- **MQA**：Q 有 H 头，K/V 只有 1 头 → KV cache 缩到 `1/H`
- **GQA**：Q 有 H 头，K/V 有 g 组（1 < g < H）→ 折中

LLaMA-2/3、GLM 等都用 GQA。代价是质量略降，但显存和访存大幅节省，推理更快。

---

## 2.6 对应 Self-Agent 哪里

- 你的 prompt caching 改造 = 让前缀 KV 可复用（本章核心挂钩）
- trace 里的 `chat glm` 耗时 = prefill + decode
- recursion_limit 间接限制 decode 的 token 总量

---

## 2.7 面试速答卡

> **Q：KV Cache 是什么？**
> A：缓存 Transformer 每层每头对每个 token 算的 K/V 向量。生成新 token 时复用前序 token 的 K/V，避免重算。我在 Self-Agent 做的 prompt caching 改造，本质就是让前缀固定以复用这部分 KV。

> **Q：为什么前缀改一个 token 整条失效？**
> A：KV 按位置存，第 i 个位置的 K/V 依赖第 0~i 所有 token（Attention 是对前面加权求和）。前缀变 → 雪崩式全失效。所以动态内容必须放末尾。

> **Q：为什么 prefill 慢 decode 快？**
> A：Prefill 处理整个 prompt，计算密集（大矩阵乘法，算力打满）；decode 逐 token，访存密集（算得少但频繁读写 KV cache，受带宽限制）。

→ [下一章：向量检索与索引](03-向量检索.md)
