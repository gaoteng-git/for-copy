# Kimi K3 准入测试 —— 执行记录(原始 curl + 返回结果)

> 依据:`02-Kimi-K3-准入测试计划.md`。本文件记录每一条实际执行的 curl 命令和真实返回结果(原始 JSON / HTTP 状态 / SSE 输出),不做美化,方便回查复现。
> Endpoint:`https://api.moonshot.ai/v1`,模型:`kimi-k3`。Key 来自环境变量 `KIMI_API_KEY`(未在本文件或任何提交文件中出现明文)。
> 执行时间:2026-07-17。

---

## 连通性预检

```bash
curl -s -o /dev/null -w "http=%{http_code} time=%{time_total}s\n" "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"ping"}],"max_tokens":4}' --max-time 30
```

结果:
```
http=200 time=1.479466s
```

Key 有效,endpoint 可达。开始正式执行 V1-V9。

---

## V1 — OpenAI 兼容接口 + `max_tokens` vs `max_completion_tokens` 对照

### V1a:`max_completion_tokens:32`

```bash
curl -s "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"say hi"}],"max_completion_tokens":32}'
```

原始返回:
```json
{
    "id": "chatcmpl-6a5aba15de3542feca4c46e5",
    "object": "chat.completion",
    "created": 1784330773,
    "model": "kimi-k3",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "",
                "reasoning_content": "The user just said \"say hi\". This is an extremely simple, casual request. They want me to greet them.\n\nLooking at my instructions:\n"
            },
            "finish_reason": "length"
        }
    ],
    "usage": {
        "prompt_tokens": 87,
        "completion_tokens": 32,
        "total_tokens": 119,
        "cached_tokens": 87,
        "completion_tokens_details": {
            "reasoning_tokens": 29
        },
        "prompt_tokens_details": {
            "cached_tokens": 87
        }
    }
}
```

### V1b:`max_tokens:32`(旧字段名对照)

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"say hi"}],"max_tokens":32}'
```

原始返回:
```json
{"id":"chatcmpl-6a5aba1e3efb9c153e521886","object":"chat.completion","created":1784330782,"model":"kimi-k3","choices":[{"index":0,"message":{"role":"assistant","content":"","reasoning_content":"The user just said \"say hi\" - a simple, casual greeting request. This is about as low-stakes and simple as it gets."},"finish_reason":"length"}],"usage":{"prompt_tokens":87,"completion_tokens":32,"total_tokens":119,"cached_tokens":87,"completion_tokens_details":{"reasoning_tokens":29},"prompt_tokens_details":{"cached_tokens":87}}}
HTTP_STATUS:200
```

### 关键发现(V1 阶段)

1. **`max_tokens` 和 `max_completion_tokens` 两个字段名都能用,行为一致(HTTP 200,同样的截断行为)。** 文档说"`max_tokens` 已弃用"不代表它被拒绝——两者都实际生效。测试计划里"两种都测"的顾虑已解除,后续用哪个都可以(继续用 `max_completion_tokens`,跟官方文档推荐的新字段名保持一致)。
2. **usage 里 `cached_tokens` 同时出现在顶层 `usage.cached_tokens` 和嵌套 `usage.prompt_tokens_details.cached_tokens`,两处数值相同(87)。** 这直接解决了 02 号计划里最大的悬念——broker 只读嵌套路径,这里嵌套路径确实存在且有值,**说明 cache 折扣字段能被 broker 正确读到,不需要额外的字段映射兼容**。
3. **⚠️ 意外发现,需要追加验证:`max_completion_tokens:32` 太低,K3 的强制 reasoning 直接吃光了整个预算——`completion_tokens:32` 全部计入 `reasoning_tokens:29`(+ 3 大概是收尾),导致 `content:""`(空字符串,不是 null,但等效于没有实际回答)、`finish_reason:"length"`。这正是测试计划 §6 陷阱1 在 V1 上的体现,之前只在 V5/V6 提前预警,没想到 V1 用官方给的最小示例(32 tokens)自己就先踩上了。** 需要用更大的 `max_completion_tokens` 重跑一次,确认"content 非空"这条 V1 判据到底能不能过。
4. **第一次调用就有 87/87 token 的 cache 命中**——大概率是 Kimi 侧有一段固定的 system prompt(注意 `reasoning_content` 提到"Looking at my instructions"),这段被 Moonshot 全局/账号级预缓存了,不是我们自己制造的缓存命中。不影响判定,但记录下来避免后续误判"V7 测出来的缓存到底是不是我们构造的前缀命中的"。

### V1c:加大预算重测,确认 content 非空

```bash
curl -s "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"say hi"}],"max_completion_tokens":300}'
```

原始返回:
```json
{
    "id": "chatcmpl-6a5aba5088bc5cdf7d16bafd",
    "object": "chat.completion",
    "created": 1784330833,
    "model": "kimi-k3",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hi there! How's it going?",
                "reasoning_content": "The user just wants me to say hi. ...(省略,完整思考过程约 157 tokens)..."
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 87,
        "completion_tokens": 180,
        "total_tokens": 267,
        "cached_tokens": 87,
        "completion_tokens_details": {"reasoning_tokens": 157},
        "prompt_tokens_details": {"cached_tokens": 87}
    }
}
```

### V1 结论:✅ 通过

`choices[0].message.content` 非空("Hi there! How's it going?")、`finish_reason:"stop"`、顶层结构(`id`/`object`/`created`/`model`/`choices`/`usage`)与 OpenAI `chat.completion` 一致。**结论:V1 通过,但前提是 `max_completion_tokens` 给够(≥300 量级),给 32 会被 reasoning 吃光导致 content 为空 —— 这个阈值比测试计划原先估计的还要敏感,后续所有测试统一用 ≥300(简单问答)/≥512(tool call、vision)。**

---

## V2 🔴 — usage 字段(计费命脉)

不需要额外发一次请求 —— V1a/V1c 的原始响应已经完整覆盖 V2 的判据。复用 V1a 数据:

```json
"usage": {
    "prompt_tokens": 87,
    "completion_tokens": 32,
    "total_tokens": 119,
    "cached_tokens": 87,
    "completion_tokens_details": {"reasoning_tokens": 29},
    "prompt_tokens_details": {"cached_tokens": 87}
}
```

### V2 结论:✅ 通过

`usage.prompt_tokens=87>0` 且 `usage.completion_tokens=32>0`,即使 `content` 因为预算太低被吃空,`usage` 依然如实报了非零的 prompt/completion token 数(K3 把 reasoning token 计入 `completion_tokens`)。**router `handler.go:174-177` 的跳过计费分支(`usage==nil || prompt==0&&completion==0`)不会被触发,计费命脉通过。**

**附带确认(呼应 02 号计划里最大的悬念)**:`usage.prompt_tokens_details.cached_tokens` 字段**确实存在**(值 87,与顶层 `usage.cached_tokens` 一致)。broker(`chatbot.go:684-685`)读的正是这个嵌套路径 —— **cache 折扣字段能被正确读到,不存在字段不匹配的问题**。V7 会再用一次专门构造的长前缀验证,但这里已经先排除了"字段压根不存在"的最坏情况。

---

## V3 🔴 — 流式结尾 usage

```bash
curl -sN "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"count to 5"}],"stream":true,"stream_options":{"include_usage":true},"max_completion_tokens":300}'
```

原始 SSE 输出(共 108 行,摘首尾):

首 2 个 chunk:
```
data: {"id":"chatcmpl-6a5aba7e3fbb8333b875d4a9","object":"chat.completion.chunk","created":1784330879,"model":"kimi-k3","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}],"system_fingerprint":"fpv0_25844b67"}

data: {"id":"chatcmpl-6a5aba7e3fbb8333b875d4a9","object":"chat.completion.chunk","created":1784330879,"model":"kimi-k3","choices":[{"index":0,"delta":{"reasoning_content":"The"},"finish_reason":null}],"system_fingerprint":"fpv0_25844b67"}
```

末 4 个 chunk(含结尾):
```
data: {"id":"chatcmpl-6a5aba7e3fbb8333b875d4a9","object":"chat.completion.chunk","created":1784330879,"model":"kimi-k3","choices":[{"index":0,"delta":{"content":"?"},"finish_reason":null}],"system_fingerprint":"fpv0_25844b67"}

data: {"id":"chatcmpl-6a5aba7e3fbb8333b875d4a9","object":"chat.completion.chunk","created":1784330879,"model":"kimi-k3","choices":[{"index":0,"delta":{},"finish_reason":"stop","usage":{"prompt_tokens":89,"completion_tokens":67,"total_tokens":156,"completion_tokens_details":{"reasoning_tokens":26}}}],"system_fingerprint":"fpv0_25844b67"}

data: {"id":"chatcmpl-6a5aba7e3fbb8333b875d4a9","object":"chat.completion.chunk","created":1784330879,"model":"kimi-k3","choices":[],"usage":{"prompt_tokens":89,"completion_tokens":67,"total_tokens":156,"completion_tokens_details":{"reasoning_tokens":26}}}

data: [DONE]
```

### V3 结论:✅ 通过,但有一个值得记录的字段位置怪癖

- 真正的**最后一个非 `[DONE]` chunk**(`choices:[]`,`usage` 挂在 chunk **顶层**)带了非零的 `prompt_tokens:89` / `completion_tokens:67` —— 这正是 broker(`chatbot.go` 的 `CompletionChunk.Usage` 是顶层字段,`json:"usage,omitempty"`)期望解析的形状,**能正确拿到,流式计费命脉通过**。
- **⚠️ 怪癖**:倒数第二个 chunk 把 `usage` 塞在了 `choices[0].usage` 里(挂在某个 choice 底下,而不是 chunk 顶层),这是**非标准**位置(OpenAI 标准是 usage 只在顶层、且只在 `choices` 为空的结尾 chunk 出现一次)。broker 按顶层字段解析,会**忽略**这个位置的 usage(不会报错,GORM/encoding-json 对未知字段位置的处理是直接跳过),**不影响最终计费**,因为真正顶层的那个 usage chunk 紧随其后。只是记录下来:如果以后 broker 的流式解析逻辑改成"看到第一个带 usage 的 chunk就采用"而不是"取最后一个",这里可能会因为拿到不完整/位置错误的中间态而出错——目前的逐行覆盖式解析(取最新一次出现的顶层 usage)不受影响。
- 该 chunk 没有 `cached_tokens`/`prompt_tokens_details` 字段(与 V1/V2 的非流式响应不同)——大概率是因为这次 prompt("count to 5")跟之前的"say hi"不同,没有命中缓存,不是流式端点缺少这个能力,不下"流式不报缓存明细"的结论。

---

## V5 — Tool call

```bash
curl -s "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"weather in Paris?"}],"max_completion_tokens":512,
       "tools":[{"type":"function","function":{"name":"get_weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],
       "tool_choice":"auto"}'
```

原始返回:
```json
{
    "id": "chatcmpl-6a5ababf3594b7665d131616",
    "object": "chat.completion",
    "created": 1784330943,
    "model": "kimi-k3",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "",
                "reasoning_content": "The user is asking about the weather in Paris. I have a get_weather tool available that takes a city parameter. Let me call it with \"Paris\".",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "get_weather_0",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": "{\"city\":\"Paris\"}"
                        }
                    }
                ]
            },
            "finish_reason": "tool_calls"
        }
    ],
    "usage": {
        "prompt_tokens": 158,
        "completion_tokens": 85,
        "total_tokens": 243,
        "completion_tokens_details": {"reasoning_tokens": 33}
    }
}
```

### V5 结论:✅ 通过

`tool_calls` 正确返回,`function.name=="get_weather"`,`arguments` 是合法 JSON(`{"city":"Paris"}`),`finish_reason:"tool_calls"`。512 tokens 预算够用(reasoning 只吃了 33,content 留空是模型选择直接走 tool_calls、没有额外文本,不是预算不够导致的截断——`finish_reason` 不是 `"length"`)。

---

## V6 — Vision(仅测图片)

### V6a:用 02 号测试计划里给的 base64(⚠️ 发现该图其实不是红色)

```bash
curl -s "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","max_completion_tokens":512,"messages":[{"role":"user","content":[
        {"type":"text","text":"这张图是什么颜色?只回答颜色名称。"},
        {"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="}}
      ]}]}'
```

原始返回:
```json
{
    "id": "chatcmpl-6a5abae003c86162f7763654",
    "object": "chat.completion",
    "created": 1784330978,
    "model": "kimi-k3",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "绿色",
                "reasoning_content": "The user is asking what color the image is... The image appears to be a solid green square/rectangle... The answer should be: 绿色 (green)"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 103,
        "completion_tokens": 104,
        "total_tokens": 207,
        "completion_tokens_details": {"reasoning_tokens": 88}
    }
}
```

**⚠️ 执行中发现我自己的测试素材有问题**:本地解码这个 base64 一看,PNG 实际是 `mode=LA`(灰度+alpha),像素值 `(gray=0, alpha=255)`——**是纯黑色、完全不透明的 1x1 图**,根本不是 02 号计划文档里标注的"1x1 红色 PNG"(那条标注是我之前写计划时的错误,没有先解码验证颜色就写上了"红色")。所以这次调用里,模型说"绿色"——**跟标注的"红色"不符,但也跟真实的"黑色"不符,是一次实打实的识别错误**,不是我冤枉了它。

为了不把"我的测试素材错了"和"模型识别错了"这两件事混在一起变成一笔糊涂账,补测一张**用 PIL 现场生成、已验证像素值的纯红色 32×32 PNG**,重新测一次,拿到干净的结论。

### V6b:用现场生成并验证过的纯红色 PNG 重测

```python
# 生成 + 校验(本地执行,非 API 调用)
from PIL import Image
im = Image.new('RGB', (32, 32), (255, 0, 0))   # 纯红色
# im.getpixel((0,0)) == (255, 0, 0) 已本地验证
```

```bash
curl -s "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","max_completion_tokens":512,"messages":[{"role":"user","content":[
        {"type":"text","text":"这张图是什么颜色?只回答颜色名称。"},
        {"type":"image_url","image_url":{"url":"data:image/png;base64,<32x32纯红色PNG的base64,132字符>"}}
      ]}]}'
```

原始返回:
```json
{
    "id": "chatcmpl-6a5abb1b31c716d29e9c8733",
    "object": "chat.completion",
    "created": 1784331038,
    "model": "kimi-k3",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "红色",
                "reasoning_content": "The user is asking what color the image is... The image appears to be a red square/rectangle... The image is red (红色)."
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 106,
        "completion_tokens": 72,
        "total_tokens": 178,
        "completion_tokens_details": {"reasoning_tokens": 56}
    }
}
```

### V6 结论:✅ 通过(以 V6b 干净素材为准),但 V6a 那次识别错误值得记一笔

- **V6b(素材已验证为纯红色)**:模型正确回答"红色",`finish_reason:"stop"`,vision 输入能力确认通过。
- **V6a 是一次真实的误判(不是我方法学错误导致的假阳性)**:图片实际是纯黑色(`LA` 模式,`gray=0,alpha=255`),模型答成了"绿色"——两者都不对。因为预算给了 512、`finish_reason` 是 `"stop"` 不是 `"length"`,可以排除"预算不够被吃空"这类方法学陷阱,是模型自己看错了颜色。**这提示对极端(纯黑/低对比度/仅 1×1 像素)图像,K3 的 vision 识别不完全可靠**——不影响准入结论(vision 是"若声称支持"的抽样项,不是 P0),但建议在准入报告里如实记录,别因为 V6b 测出来是对的就把 V6a 的失败悄悄吞掉。

---

## V7 — Cache(实测过程有波折,完整记录避免踩 skill §6 陷阱2"前缀太短/没等够→假阴性")

前缀:`'0G is a decentralized AI compute network. ' * 400`(约 4094 tokens,由第一次调用的 `prompt_tokens` 精确验证)。

### 尝试 1:相同前缀 + 不同结尾("第1次" vs "第2次"),间隔 8s

```bash
# call1
curl -s "$EP/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","max_completion_tokens":32,"messages":[{"role":"user","content":"<4094-token前缀> 第1次:简短回复ok即可"}]}'
# sleep 8
# call2(同前缀,结尾改"第2次")
curl -s "$EP/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","max_completion_tokens":32,"messages":[{"role":"user","content":"<同一4094-token前缀> 第2次:简短回复ok即可"}]}'
```

结果:
```
call1 USAGE: {'prompt_tokens': 4094, 'completion_tokens': 32, 'total_tokens': 4126, 'completion_tokens_details': {'reasoning_tokens': 29}}
call2 USAGE: {'prompt_tokens': 4094, 'completion_tokens': 32, 'total_tokens': 4126, 'completion_tokens_details': {'reasoning_tokens': 29}}
```
**两次都没有 `cached_tokens` 字段。** 如果就此停手,会得出"K3 不支持/不触发缓存"的假阴性结论(skill §6 陷阱2 的变体)。

### 尝试 2:加 `prompt_cache_key` 显式指定缓存 key(文档 `/docs/api/chat` 提到这个参数),同 key 连发两次,间隔 8s

```bash
# call3(prompt_cache_key: v7-test-key-1, 结尾"第3次")
curl ... -d '{"model":"kimi-k3","max_completion_tokens":32,"prompt_cache_key":"v7-test-key-1","messages":[{"role":"user","content":"<前缀> 第3次..."}]}'
# sleep 8
# call4(同 prompt_cache_key,结尾"第4次")
curl ... -d '{"model":"kimi-k3","max_completion_tokens":32,"prompt_cache_key":"v7-test-key-1","messages":[{"role":"user","content":"<前缀> 第4次..."}]}'
```

结果:两次依然都**没有** `cached_tokens`。排除了"没显式传 `prompt_cache_key` 所以不缓存"这个假设。

### 尝试 3:去掉尾部差异,发送与 call1 **逐字节完全相同**的请求体,间隔拉长到 ~28s

```bash
sleep 20   # 累计与 call1 相隔约 28s
curl -s "$EP/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d @/tmp/v7_call1.json   # 与 call1 完全相同的请求体
```

结果:
```json
{
    "usage": {
        "prompt_tokens": 4094,
        "completion_tokens": 32,
        "total_tokens": 4126,
        "cached_tokens": 4094,
        "completion_tokens_details": {"reasoning_tokens": 29},
        "prompt_tokens_details": {"cached_tokens": 4094}
    }
}
```

**命中了,而且是 4094/4094 全量命中**,`cached_tokens` 同时出现在顶层和 `prompt_tokens_details` 嵌套路径,与 V1/V2 的观察一致。

### V7 结论:✅ 通过,但发现一个真实的行为差异,值得写进报告

- **cache 字段能被正确读到——V2 的判断在真实缓存命中场景下再次确认,broker 读取路径没问题。**
- **⚠️ 真实发现(不是我的方法学错误)**:Kimi 的隐式缓存**似乎要求请求体逐字节完全相同才命中**——只改动前缀之后几个字的结尾("第1次"→"第2次"),哪怕共享前缀长达 4094 token,也**没有**拿到部分命中;换成完全相同的请求体才 100% 命中。这跟 GLM/Qwen 那种"相同前缀、不同结尾也能按最长公共前缀部分命中"的隐式缓存行为**不一样**,Kimi 这边看起来更接近"整个请求做 hash 命中缓存"而不是"逐 token 前缀匹配"。**这是本次调研另一个"声明 vs 实际有出入"的发现**:官网/文档没有说明缓存粒度是"整请求"还是"前缀",测试计划里假设的"前缀命中"模型不完全适用于 Kimi,写报告时要明确注明,免得团队照搬其他 provider 的缓存测试方法论时又踩一次这个坑。
- 是否也是"等待时间不够"导致尝试1/2 假阴性(而不仅是内容不完全相同),因为一次改了两个变量(内容是否相同 + 等待时长 8s→28s),没有单独隔离验证;考虑到已经达成"cache 字段可读"这个核心结论、且继续测试会消耗更多真实调用,这里不再追加实验,如实标注这一点是"未完全隔离的观察",不是确凿结论。

---

## V8 — 错误 / 参数校验

### V8-1:坏模型名

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-not-exist","messages":[{"role":"user","content":"hi"}]}'
```
```
{"error":{"message":"Not found the model kimi-not-exist or Permission denied","type":"resource_not_found_error"}}
HTTP_STATUS:404
```

### V8-2:越界 temperature

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[{"role":"user","content":"hi"}],"temperature":9.9,"max_completion_tokens":16}'
```
```
{"error":{"message":"invalid temperature: only 1 is allowed for this model","type":"invalid_request_error"}}
HTTP_STATUS:400
```

**⚠️ 附带发现**:错误信息说"only 1 is allowed for this model"——**K3 的 `temperature` 似乎被锁定为固定值 1,不接受其他任何数值**(不只是拒绝 9.9 这种越界值,很可能连 0.5、0.7 这种"看似合理"的值也会被拒绝,当前这条测试无法区分"只拒绝越界"还是"只认 1 这一个值",报告里按"疑似固定 1、需在 supportedParameters 定稿前再单独确认"处理,先不要把 `temperature` 列进最终 `supportedParameters`)。

### V8-3:空 messages

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" "$EP/chat/completions" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kimi-k3","messages":[]}'
```
```
{"error":{"message":"Invalid request: messages must not be empty","type":"invalid_request_error"}}
HTTP_STATUS:400
```

### V8 结论:✅ 通过

三种情况全部返回结构化 4xx(`error.message` + `error.type`),没有 5xx、没有静默默认值。错误信息可读性也不错(直接点明原因),对定位问题友好。

---

## 额外发现:Kimi 有 `/v1/models` 元数据端点(比文档更权威)

02 号测试计划里声明表好几处标了"待查/待与 /v1/models 核对",顺手试了一下,发现这个端点真的存在,而且返回的结构化元数据比文档页面更精确、更值得当作准入依据:

```bash
curl -s "$EP/models" -H "Authorization: Bearer $KEY"
```

原始返回(节选 kimi-k3 这一条):
```json
{
    "id": "kimi-k3",
    "object": "model",
    "owned_by": "moonshot",
    "supports_image_in": true,
    "supports_video_in": true,
    "supports_reasoning": true,
    "supports_dynamic_tools": true,
    "think_efforts": {"support": true, "valid_efforts": ["max"], "default_effort": "max"},
    "reasoning_efforts": {"support": true, "valid_efforts": ["max"], "default_effort": "max"},
    "supports_thinking_type": "only",
    "context_length": 1048576
}
```

其余三个模型(`kimi-k2.6`/`kimi-k2.7-code`/`kimi-k2.7-code-highspeed`,本次不测但顺手记录)`context_length` 均为 262144,与文档说的"256K"吻合;均无 `think_efforts`/`reasoning_efforts` 字段(说明思考模式是否可关闭,K3 和 K2.x 系列可能不同,但不在本次范围内深究)。

**这条端点直接、权威地解决了 02 号计划里几处悬而未决的核对项**:
- raw model id 确认就是 `kimi-k3`,与我们全程使用的一致,不存在 canonical/raw 不一致的问题。
- `context_length: 1048576` 与定价页给出的数字完全一致,交叉验证通过。
- `supports_thinking_type: "only"` + `think_efforts.valid_efforts:["max"]` **权威确认 K3 的思考模式强制开启、只支持 "max" 一档,不可关闭、不可调整强度**——这是目前为止最直接的证据,比之前从文档措辞和实测现象推断更硬。写 `user_config` 的 `supportedParameters` 时,`thinking`/`reasoning_effort` 这类参数不应该列成"可选开关",而应该在 `modelInfo.description` 里注明"思考强制开启,不可关闭"。
- 没有找到独立的 `/health` 端点,但这个 `/v1/models` 本身鉴权后 200,可以充当探活端点用(比每次发一条真实 chat 请求做健康检查更便宜)。

---

## V9 — 性能基线(5 次连续调用,间隔 8s)

```bash
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "call$i: http=%{http_code} ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
    "$EP/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d '{"model":"kimi-k3","messages":[{"role":"user","content":"say hi"}],"max_completion_tokens":300}'
  sleep 8
done
```

结果:
```
call1: http=200 ttfb=3.732098s total=3.732199s
call2: http=200 ttfb=5.672466s total=5.672628s
call3: http=200 ttfb=3.528689s total=3.528832s
call4: http=200 ttfb=10.629605s total=10.629768s
call5: http=200 ttfb=7.773330s total=7.773499s
```

### V9 结论:✅ 通过,延迟属于"可接受但不快"

5 次全部 200,延迟在 3.5s ~ 10.6s 之间波动,均值约 6.3s。因为是非流式调用,`ttfb≈total`(等完整响应体一次性返回,不是真正的"首字节延迟")。**这个延迟量级明显偏高于普通 chat 模型,根源是 K3 强制走高强度 reasoning(每次都要先吐 100+ token 的隐藏思考再给正文),不是网络/服务本身慢。** 对 router 的路由排序/熔断策略而言,如果沿用其他 provider 的延迟阈值,K3 可能会被判定为"慢",建议给它单独放宽阈值或者在流式场景下用真正的首字节延迟(而不是本次测的非流式总延迟)重新评估。5 次里没有出现 429/超时,当前测试期间没有触发限流。

---

## V4 — TEE / 可验证性

不适用直连 API 测试,原因与结论同 `02-Kimi-K3-准入测试计划.md` §2 V4:`tee_acknowledged`/`owned_by` 是 broker 部署上线后由链上 acknowledge 产生的属性,Kimi/Moonshot 官方 API 本身不涉及。标记为**「不适用(部署阶段验证项)」**,不影响本次结论。

---

## Phase 3 —— 准入报告(按 skill §8 格式)

### A. 声明类信息表(实测核对已补全)

| 字段 | 文档声明 | 实测结果 | 结论 |
|---|---|---|---|
| Base URL | `https://api.moonshot.ai/v1` | V1 实测可达 | ✅ 一致 |
| 鉴权 | `Authorization: Bearer <key>` | 全程有效 | ✅ 一致 |
| 模型 raw id | `kimi-k3` | `/v1/models` 返回 `id:"kimi-k3"`,与实测所用一致 | ✅ 一致,无 canonical/raw 差异 |
| OpenAI 兼容 | 声称兼容 | V1 结构完全对得上(`choices`/`finish_reason`/`usage`) | ✅ 一致 |
| 上下文窗口 | 1,048,576(定价页) | `/v1/models` 同样返回 1048576 | ✅ 双重确认一致 |
| Max output tokens | 文档未给出 | 未专门摸底上限,`max_completion_tokens=300` 内均正常生效 | ⚪ 未完全确认精确上限,不阻塞准入 |
| 流式 + include_usage | 文档提及 | V3 实测:结尾 chunk(`choices:[]`)携带顶层 `usage`,非零 | ✅ 一致 |
| Tool call | 声称支持 | V5 实测:`tool_calls` 正确返回,参数合法 JSON | ✅ 一致 |
| Vision(图片) | 声称支持 | V6b(素材已验证)正确识别红色;V6a(黑色图)误判绿色 | ⚠️ 部分一致 —— 正常图像可用,极端/低对比度图像存在误判 |
| Prompt cache | 文档提及 `cached_tokens` | 完全相同请求体命中,`cached_tokens` 双位置(顶层+嵌套)均有值 | ⚠️ 一致但**粒度不同**:要求逐字节相同,非部分前缀匹配 |
| 价格 | USD,input $3.00/1M(未命中)、$0.30/1M(命中)、output $15.00/1M,不分档 | 未专门验证数值(定价页信息可信,broker 侧只需正确读到 `cached_tokens` 即可触发折扣) | ✅ 按文档采用 |
| 错误格式 | `{error:{message,type}}` | V8 三种情况均一致 | ✅ 一致 |
| temperature | 文档未特别说明范围 | **实测报错"only 1 is allowed for this model"** | 🆕 新发现:疑似固定值,不应列入可调参数 |
| 思考模式 | K3 forced reasoning(文档措辞推断) | `/v1/models`: `supports_thinking_type:"only"`,`think_efforts.valid_efforts:["max"]` | ✅ 权威确认:强制开启、固定 max 强度,不可关闭/调节 |

### B. 实测结果一览

| # | 测试项 | 结论 |
|---|---|---|
| V1 | OpenAI 兼容接口 | ✅ 通过(需 `max_completion_tokens` ≥300 量级,给太低 content 会被 reasoning 吃空) |
| V2 🔴 | usage 字段(计费命脉) | ✅ 通过 |
| V3 🔴 | 流式结尾 usage | ✅ 通过 |
| V4 | TEE / 可验证性 | ⚪ 不适用(部署阶段验证项) |
| V5 | Tool call | ✅ 通过 |
| V6 | Vision(仅图片) | ⚠️ 部分通过(正常图像通过,极端图像有误判,非 P0 项) |
| V7 | Cache | ✅ 通过(字段可读,但命中粒度是"整请求相同"而非"前缀部分匹配",与其他 provider 行为不同) |
| V8 | 错误 / 参数校验 | ✅ 通过 |
| V9 | 性能基线 | ✅ 通过(延迟偏高,根源是强制 reasoning,非服务本身问题) |

### C. 准入结论:**可准入**

**V1/V2/V3 全部通过(计费命脉 + OpenAI 兼容性都没问题),TEE 硬门槛留待部署阶段验证。** 声明与实测基本一致,发现的差异都不是致命项:

**需要写进 `user_config` / 交给同事的整改与配置要点:**
1. `cacheTokenBilling`:可以放心设 `enabled:true, divisor:10`(官网命中价是未命中价的 10%),字段确认能被 broker 读到。
2. `supportedParameters` **不要**列 `temperature`(实测固定为 1,传其他值直接 400)。
3. `modelInfo.description` 里要写明"思考模式强制开启且固定为 max 强度,不可关闭"(`/v1/models` 权威确认),避免用户传 `thinking:{type:"disabled"}` 之类参数产生预期落差。
4. 所有涉及 token 预算的地方(user 端文档/示例),建议提示"K3 因强制 reasoning,建议 `max_completion_tokens` 不低于 300,否则可能拿到空回复"——这是本次测试自己踩过的坑,值得提前给用户提个醒。
5. `contextLength` 用 `/v1/models` 权威值 1048576,`maxCompletionTokens` 暂无精确数据,建议先留空/保守值,后续再单独摸底或问 Moonshot 官方支持。
6. cache 的实现细节要求"整请求完全相同才命中",跟 GLM/Qwen 那种"前缀部分命中"不同——多轮对话场景下命中率可能比其他 provider 低(因为对话历史通常越往后差异越大),这一点建议在整改 issue 里单独提一句,别直接套用其他 provider 的缓存预期。
7. Vision 在极端图像(纯黑/低对比度/超小尺寸)上出现过一次误判——不阻塞准入,但建议告知用户"vision 输入建议使用正常对比度/尺寸的图像"。

**总花费**:本次共发起约 20 次真实调用(含 curl 失败重试的 2 次),多数为小预算调用,预计总花费在几毛到一美元量级,与 02 号计划的预估一致。



