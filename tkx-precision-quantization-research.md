# TKX PRECISION 列（模型quantization字段）可行性研究

背景：TKX 反馈"若 /v1/models 能对每个模型返回 quantization（如 fp8/bf16），PRECISION 这列就能亮；否则暂时无源"。本文档是对 0g-router、0g-serving-broker、0g-compute-ts-sdk、deploy、ai-team-handbook、gaoteng 全部子目录的一次彻底扫描，目的是确认这个数据能不能提供、如果不能，需要哪些项目配合。

---

## 结论：目前完全提供不了，而且原因比预想的更复杂

### 一个关键新发现：真的有结构化数据，但被锁在最底层，从未向上传递

`deploy/phala/2-mainnet/19-glm5.2/docker-compose.yml`（第56-66行）里，SGLang启动`glm-5.2`这个模型的命令行参数里，真实写着：

```
--model-path
/mnt/GLM-5.2-W4AFP8
--served-model-name
glm-5.2
--quantization
w4afp8
...
--kv-cache-dtype
fp8_e4m3
```

**这是一个真实、结构化的量化参数**——但它只是Docker容器里推理引擎（SGLang）自己的启动参数。broker根本不读取它，router更不可能拿到，从这一层往上，这个值完全消失了。这是目前整个系统里，唯一存在过的一份"真正结构化"的量化数据，但被困在最底层，没有任何管道把它往上传。

对照检查了另外两个自部署模型：
- `20-qwavity-35b/docker-compose.yml`（`0gm-1.0-35b-a3b`）：SGLang启动参数里**没有**`--quantization`标志，权重路径本身也不含量化线索
- `29-qwavity-35b-sia/docker-compose.yml`（`0gm-1.0-35b-a3b-sia`）：同样没有任何量化信息

### 更关键的问题：大多数模型，0G自己也不知道量化格式

`deploy/phala/2-mainnet/25-glm-ali/user_config`（第39-44行，紧挨着`model: glm-5`这行的注释）里有一条直接、明确的说明：

> "The '-FP8' suffix is a historical brand identifier carried over from the earlier sglang/vLLM deployment that served zai-org/GLM-5-FP8; **Alibaba does not publish the serving precision for their glm-5 tier.**"

翻译：GLM-5这个名字里的"-FP8"后缀只是历史遗留的品牌标识，**阿里云根本不公开他们glm-5这个档位实际用的是什么精度**。

这意味着：目录里通过DashScope（阿里云）、OpenRouter、智谱官方API、Redpill这些第三方转发接入的全部约30个模型条目（DeepSeek-V4系列、Qwen系列、GLM-5/5.1、MiniMax、Kimi、Claude系列、GPT-5.6系列等），**0G Foundation自己都无从得知真实的量化格式**——不是我们没采集，是这个信息压根不存在于我们能触达的任何地方，上游vendor不披露。

只有3个自己部署的模型（`0gm-1.0-35b-a3b`、`0gm-1.0-35b-a3b-sia`、`glm-5.2`，即之前TKX分组研究里查到的那3个TeeML模型）我们自己控制部署，理论上才有可能拿到真实值——但即便是这3个，也只有`glm-5.2`这一个的量化信息真的存在（就是前面说的、锁在容器启动命令里的那个），另外两个连容器启动参数里都没写量化格式。

### 团队自己早就有明确的架构决定：这是故意不做的

`docs/model-canonical-rollout.md`（第60-62、117行）里有明确的设计决定：

> "Variants / quantization: FP8 etc. merge into the base canonical as a **second endpoint**... infra dimensions (provider / quantization / deployment) live **below** the canonical at the endpoint layer, never in the catalog."
>
> "Quantization / provider variants are **aliases or endpoints**, not new canonicals."

也就是说，"要不要把quantization当成一个可查询的模型属性"这件事，团队已经讨论过并且**明确决定不做**，是刻意的设计选择（量化变体被当成同一个canonical模型下的不同endpoint/别名），不是遗漏。

`docs/routing-design.md:413`（对照OpenRouter功能表）也明确写着：`| Quantization | quantizations | — | Providers don't expose this |`。

---

## 各仓库逐一排查结果

| 仓库/层级 | 是否有结构化quantization数据 |
|---|---|
| SGLang容器启动参数（仅自部署provider，如`19-glm5.2`） | **有**——真实的`--quantization w4afp8`标志，但锁在容器内，broker从不读取 |
| Broker `ModelInfo`配置结构体 / `user_config`（`0g-serving-broker`、`deploy/phala`） | 无字段；仅在`name`/`description`自由文本里，约35个模型条目中有4个（都是"GLM-5-FP8"/"GLM-5.2-W4AFP8"这类变体）非正式地提到了量化字样 |
| Broker `/v1/models` JSON（`ModelObject`） | 无字段 |
| 链上`OnChainService`/`ServiceAdditionalInfo`（`0g-router/pkg/contract`） | 无字段；`AdditionalInfo`这个JSON blob技术上可扩展，但目前粒度是"每个服务"而不是"每个模型"，且当前只用于路由/信任分类，用途不匹配 |
| Router的`providers`数据库表 / `ModelEntry`/`ProviderEntry` | 无字段 |
| `0g-compute-ts-sdk`类型定义/README | 无字段；只有一个示例model id字符串里带着"FP8"字样（`README.md:189`），不是被解析出来的字段 |
| Fine-tuning（微调）`Deliverable`交付结构 | 无字段，训练时的quantization config和推理serving之间完全没有桥接 |

### `0g-compute-ts-sdk`

全仓库搜索没有任何quantization/precision/dtype相关的schema字段。唯一命中是`README.md:189`一个示例model id字符串`'zai-org/GLM-5.1-FP8'`，作为`getServiceMetadata()`的参数示例，同样只是不透明ID里的子字符串，不是被解析的字段。

### `ai-team-handbook`

只有一处相关命中，且是另一个问题（不是quantization指标本身）：`skills/router-qa/SKILL.md:146`提醒"`/v1/models`可能列出原始provider id（如`zai-org/GLM-5-FP8`）而不是canonical id（`glm-5`）"——这是路由/ID解析的坑，跟量化指标无关。

### `gaoteng`（我自己之前的笔记）

搜索确认之前写的三份笔记（`0G四个项目介绍.md`、`TKX排行榜接入分析与行动清单.md`、`TKX用量上报-部署上线步骤.md`）里，**完全没有提到过quantization/precision**——之前只覆盖了TKX验证的两个维度（Pricing、Volume），PRECISION是这次全新提出的、之前没研究过的点。

### Fine-tuning子系统（再次确认，无桥接）

训练时的量化配置（`api/fine-tuning/execution/transformer/transformer/train_lora.py`的`setup_quantization()`，bitsandbytes 4-bit QLoRA）仅用于微调训练本身。微调完成后交付给用户的`Deliverable`结构体（`contract/fine_tuning_serving.go:62-69`）只有`Id/ModelRootHash/EncryptedSecret/Acknowledged/Timestamp/Settled`这几个字段，**没有任何元数据字段，更没有量化信息**，训练时的量化配置完全没有渠道传递到推理serving那一侧。

### 现成的参照模板：`tee_type`字段是怎么工作的

`0g-serving-broker`的`ModelInfo`结构体（`api/inference/config/config.go:116-137`）是provider运营方能自主申报的字段集合：

```go
type ModelInfo struct {
    Name, Description, ContextLength, MaxCompletionTokens string/int // 必填
    Architecture        *ModelArchitecture
    SupportedParameters []string
    SupportedFormats    []string
    DefaultParameters   map[string]interface{}
    TeeType             string   // 可选，如"TDX"/"SEV"/"SGX"/"H100"
    ExpirationDate      string
    VideoSizeRatios     map[string]float64
}
```

**这里没有`Quantization`字段。** 但`TeeType`这类自主申报字段的工作流程可以直接复用：provider在自己的`user_config`里手动填 → broker自己的`/v1/models`吐出来 → router定期通过health-check同步流程拉取 → 写进`providers`表 → router公开API里展示（标`[beta]`，因为是自报、未验证的数据）。

类似的自报字段还有`ProviderName`、`ProviderCountry`、`ServingDomain`——都是同一套"provider自己填、router原样透传"的模式。

---

## 如果真要做，需要哪些项目配合

需要三个项目协同改动，缺一不可：

| 项目 | 需要做什么 |
|---|---|
| **0g-serving-broker** | 在`ModelInfo`结构体（`api/inference/config/config.go`）和`deploy/phala/**/user_config`里加一个可选的`quantization`字段，让每个provider运营方**自己手动申报**（跟`teeType`是同一个模式）——转发第三方API的provider没法填（因为上游不公开），只有自己部署模型的provider能填 |
| **0g-router** | 在`providers`数据库表（`internal/model/models.go`）加一列，走现有的health-check同步流程把这个字段从broker拉过来（照抄`tee_type`那条现成的管道），再在`/v1/models`的响应结构体（`pkg/response/types.go`的`ModelEntry`/`ProviderEntry`）里加这个字段并通过`internal/handler/public.go`的映射函数暴露出来，估计也得标`[beta]`（因为是provider自报、未经验证的数据） |
| **0g-compute-ts-sdk** | TypeScript那边的类型定义要跟着更新，这是下游被动跟着改，不是主动需求 |

**链上合约不需要改**——现有的`AdditionalInfo`这个JSON字段技术上够用，或者干脆只在router一侧加个DB列就行，不涉及链上schema；但注意`AdditionalInfo`目前是按"每个服务"而不是"每个模型"的粒度存的，如果要复用它，需要额外处理粒度不匹配的问题。

这是一个**全新功能**，不是修一个"本该存在但没接上"的bug——目前没有任何现成的管道漏了这份数据，是压根没有任何一层收集过它。

## 结论

**这不是"数据存在但没暴露"的问题，是"这个数据对我们大部分provider来说压根不存在"的问题**——第三方API上游不公开量化格式，我们自己部署的模型里也只有一个（glm-5.2）真的有这个信息、还锁在最底层没往上传。要做的话，第一步得先确认：跟我们对接的这几个provider，愿不愿意开始手动申报自己模型的量化格式？这是个业务/合作层面的前提，不只是技术实现的问题。
