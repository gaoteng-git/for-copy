# 0g-router / 0g-serving-broker 架构总结(embedding 接入笔记)

## 0g-router 核心功能(一句话:聚合网关)

它是用户唯一要打交道的入口,像一个"AI 算力界的淘宝"——用户不用管背后具体是哪家厂商在提供服务,只管调用统一的接口。核心做四件事:

1. **鉴权**:验证用户身份(API key/钱包签名),管理用户余额。
2. **选 provider**:一个请求进来(比如要 embedding),从注册的一堆 provider 里,按价格、能力、健康状态挑一个最合适的转发过去,失败了自动换下一个。
3. **计费**:根据 provider 返回的 usage,算这次该收用户多少钱,记进 Router 自己的账本。
4. **对外统一格式**:不管背后 provider 用的是什么协议,Router 保证用户看到的永远是标准的 OpenAI 兼容格式。

## 0g-serving-broker 核心功能(一句话:provider 的门面 + 收银台)

这是"provider"这个角色要跑的软件,每个 provider(不管是转发阿里云还是自建 GPU)都跑同一份代码,只是配置不同。核心做四件事:

1. **对外暴露服务**:注册在链上,声明自己的价格、模型、TEE 验证方式,好让 Router 能发现它。
2. **转发请求**:收到 Router 转来的请求,转给自己真正的算力来源(阿里云 API,或者自己的 GPU)。
3. **算钱 + TEE 签名**:根据上游返回的真实 usage 算这次该收多少钱,并在可信硬件环境(TEE)里给响应签名,证明"这确实是我这个可信环境算出来的,没被篡改"。
4. **链上结算**:定期(event 进程)把攒下来的账,提交到链上,把钱从付款方账户转到自己账户。

---

## 一个 embedding 请求的完整旅程

```
用户
 │  POST /v1/embeddings（带 API key，body 是 {"model":"qwen3.7-text-embedding","input":"..."}）
 ▼
┌─────────────────── 0g-router ───────────────────┐
│ ① 鉴权：验证 API key，查用户余额够不够            │
│ ② 查 feature flag：FEATURES_EMBEDDING_ENABLED    │
│    开着才认这条路由，否则直接 404                 │
│ ③ 查模型注册表：models.yaml 里有没有这个模型       │
│ ④ 选 provider：按价格/健康状态，挑一个跑这个       │
│    模型的 provider（比如我们接入的这一个）        │
│ ⑤ 用 Router 自己那把 TEE 钱包签发一个临时 session  │
│    key（这一步之后，provider 眼里只认 Router，    │
│    不知道背后是哪个真实用户）                     │
└───────────────────┬───────────────────────────┘
                     │ 转发请求（带上第⑤步的临时 key）
                     ▼
┌────────────── provider 的容器们 ──────────────────┐
│ ⑥ broker-ingress：TLS 解密，反代给下面的 broker    │
│ ⑦ broker 主进程：                                 │
│    - 验证第⑤步的 session key                     │
│    - 转发给真正的上游（这次是阿里云 DashScope）    │
│    - 拿到阿里云的响应，读 usage.prompt_tokens      │
│    - 按配置的单价算这次该收多少钱，记进本地数据库  │
│    - 在 TEE 里给响应签名（ZG-Res-Key）             │
│    - 把响应传回 broker-ingress                    │
│ ⑧ broker-ingress：加密，传回公网                  │
└───────────────────┬───────────────────────────┘
                     │ 响应原路返回
                     ▼
┌─────────────────── 0g-router ───────────────────┐
│ ⑨ 验证 TEE 签名（确认响应没被篡改）                │
│ ⑩ 按 Router 自己的计价（面向用户的价格，可能跟     │
│    provider 收的成本价不同），从用户余额里扣钱     │
│ ⑪ 把响应转发给用户                                │
└───────────────────┬───────────────────────────┘
                     ▼
                   用户收到 embedding 向量
```

**旅程之外,还有两件"事后"才发生的事**(不阻塞这次请求,是定期批处理):

- **broker 自己的 event 进程**:每隔一段时间,把本地数据库里攒的"Router 欠我多少钱",打包提交上链结算(钱从 Router 的链上钱包转到 provider 的链上钱包)。
- **Router 自己的资金池**:用户的钱一开始是存进 Router 自己的 `RouterPayment` 合约里的,Router 定期批量从这个合约里,按每个真实用户各自扣款——这一步跟 provider 完全无关,是 Router 自己内部的账。

**一句话总结全貌**:用户只跟 Router 打交道;Router 对每个 provider 来说,自己就是唯一的"客户";provider 只管转发+算钱+签名,不知道真实用户是谁;两段资金流转(用户→Router、Router→provider)各自独立、互不知情,靠 Router 这一个身份串起来。

---

## 补充:"抹平接口小差异"这件事,发生在哪里

**在 `0g-serving-broker` 的 `PrepareHTTPRequest` 里,而且只对 chat 类型生效**——broker 不是一个能把任意厂商私有协议翻译成 OpenAI 格式的万能翻译器,它假设接入的上游本来就已经是 OpenAI(或 Anthropic)兼容的;`PrepareHTTPRequest` 只是在这个前提下,对 **`svcType == "chatbot"`** 的请求做一些局部的字段级微调(比如 `max_tokens`↔`max_completion_tokens` 换名字、把通用的 `reasoning_effort` 翻译成目标模型自己原生的"思考强度"控制方式)。**embedding 请求完全绕开这套逻辑,body 从 router 到 broker 到上游全程一个字节都不改**——这次能这么顺利接入阿里云,是因为阿里云自己在 `/compatible-mode/v1/embeddings` 这个 endpoint 上已经做好了 OpenAI 兼容层,不需要 broker 帮忙翻译。
