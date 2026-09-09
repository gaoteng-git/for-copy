# Embedding 接入相关 commits 全览（0g-router + 0g-serving-broker）

统计时间：2026-09-09，基于用户本地刚 pull 完的两个仓库 main 分支最新代码。

## 搜索方法（保证"全"）

两个仓库都做了两遍交叉核对：

1. `git log --grep="embed"`（大小写不敏感，扫全部 main 提交）——0g-router 共排查 38 条候选，0g-serving-broker 共排查 12 条候选。
2. 对 embedding 专属源文件做 `git log --follow` 文件级历史交叉验证：
   - 0g-router：`backend/pkg/inference/embedding_handler.go`、`backend/pkg/inference/embedding_handler_test.go`
   - 0g-serving-broker：`api/inference/internal/ctrl/embedding.go`、`api/inference/internal/ctrl/embedding_test.go`

逐条读了每个候选的完整 commit body，排除了以下几类纯字面撞词的假阳性：
- "embedded registry"（`models.yaml` 内嵌加载器，`go:embed`）
- "embedded wallet"（Privy 相关）
- "refactor: embed nginx configuration in docker-compose.yml"
- 其余零散的 "embeds"/"embedded" 作为普通英语单词使用（如 "the error message embeds the sentinel"）

---

## 0g-router（按 PR 号顺序，共 5 条真正相关 + 1 条捎带提及）

| commit | PR | 日期 | 描述 |
|---|---|---|---|
| `a3cf352` | **#753** | 2026-09-04 | 主体接入 PR——把 qwen3.7-text-embedding 接进 Router：新增 `embedding_handler.go`、`service_type=embedding`、`models.yaml` 注册、计费兜底（usage 缺失时的估算逻辑）等全套代码。 |
| `b4fa423` | #800（捎带提及，非独立改动） | 2026-09-07 | Pay v2 结算模式重构 PR；作者在开发分支上也顺手修过 `embedding_handler.go` 的编译错误，但合并进 main 时这部分 diff 没有落地（已被 #801 覆盖），最终只留下给测试 fixture 补一个 `SettlementMode` 字段。 |
| `8fc8b1c` | **#801** | 2026-09-04（PR 序号晚于 #753，实际按 #801 排在 #753 之后） | 修复 #753 遗留的编译错误：main 上 E2EE 工作给 `VerifyTEESignature` 加了第 5 个参数 `reqBody`，其余 6 个 handler 调用点都传了，唯独 `embedding_handler.go` 漏传（因为是并行分支开发的）。 |
| `bb63ee3` | **#804** | 2026-09-07 | 在 `mainnet-staging.tfvars` 里把 `features_embedding_enabled` 打开，三步验证流程的第①步（对应"code change → terraform apply → deploy"三步走里的第一步）。 |
| `170060d` | **#817** | 2026-09-08 | 修复 Router 同步逻辑里 `fanOutPrices` 的价格门槛 bug——原来要求 prompt 和 completion 单价都严格大于 0 才准入，embedding 结构上不可能有 completion 价格，导致这个 provider 一直进不了 `providers` 表；顺带修了一个由"放行 embedding"暴露出的潜在计费漏洞（echo 回来的 `completion_tokens` 会被按默认单价错误计费）。 |
| `7a2ae40` | **#826** | 2026-09-09 | 把 `mainnet.tfvars` 里的 `features_embedding_enabled` 翻成 `true`，正式在 prod 开放 `POST /v1/embeddings`（同一个 commit 还捎带翻了一个跟 embedding 无关的开关：新用户默认 USD 结算）。 |

> 注：`8fc8b1c` 和 `a3cf352` 的 committer date 都显示 2026-09-04（大概率是 rebase 时被覆盖），但按 PR 序号和 commit body 的描述（"修复 #753 遗留的编译错误"），`8fc8b1c` 在实际开发时序上是晚于 `a3cf352` 的后续修复。

---

## 0g-serving-broker（共 1 条）

| commit | PR | 描述 |
|---|---|---|
| `1be7b2f` | **#673** | 主体接入 PR——broker 侧新增 `ctrl/embedding.go`（响应解析、usage 兜底、批量输入处理）。**这一个 commit 里已经包含了 E2EE 的 `nonChatRoutes` 排除表加 `/embeddings` 这条**（`TestEveryChatRouteHasARecognizedSurface` 需要的那个修复）——因为 PR 合并时做了 squash，之前单独提的那个修复分支内容被并进了这一个 commit，main 上看不到独立的第二条记录。 |

`git log --follow` 对 `ctrl/embedding.go`/`embedding_test.go` 两个文件的完整历史都只指向这一个 commit，确认 broker 这边没有后续的 embedding 专属修复落到 main 上。
