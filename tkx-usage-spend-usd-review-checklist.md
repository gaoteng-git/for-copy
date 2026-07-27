# `spend_usd_24h` Review Checklist — Final Verification

基准 commit：`b8c1ed6aae4561a3be906d9e86b5885d2720e934`（feature/tkx-usage-spend-usd 分支起点）
核对时间：2026-07-27
分支：`feature/tkx-usage-spend-usd`（HEAD: `3a7c84f`）

验证方式：`go build ./...` / `go vet ./...` / `go vet -tags=integration ./...` / `go test -count=1 ./...` 全绿；`git diff b8c1ed6..HEAD` 逐文件核对；全仓库 grep 排查悬空引用；设计文档内所有代码行号引用与测试函数名逐一核对。

## 逐项结果

| # | 建议 | 状态 | 说明 |
|---|---|---|---|
| **MEDIUM — changelog / 设计文档过期措辞** |||
| 1 | `main.go:88` 陈述 mainnet 已启用 | ✅ 已修复 | 现文本："on mainnet as of the 2026-07-22 milestone flip" |
| 2 | 设计文档 `:213` 对应行删掉 | ✅ 已修复 | 已从"上线后的下一步"移除，列表重新编号为 2 条 |
| 3 | 设计文档 `:199` 对应行改过去式 | ✅ 已修复 | "`tkx_usage_enabled` 现已是 `true`——staging 验证通过后已按发布流程翻过" |
| 4 | 批准记录写进设计文档，替换掉被删掉的 checklist | ✅ 已修复 | 独立 blockquote，位于"上线后的下一步"标题正上方；记录 @Ravenyjh 于 2026-07-27 批准 |
| **HIGH — 公开 money 数字的静默降级路径** |||
| 5 | malformed 分支删掉或改 SQL 层哨兵，注释改准确 | ⚠️ 按最终指示处理 | 未删分支、未加 SQL 哨兵；`if !ok { continue }` 保留，注释压成一行准确描述（"SQL 产出，恒为合法整数串；此处仅作 nil 安全"），`TestBuildTKXUsageReport_MalformedTotalCostUsdTreatedAsZero` 已删除——匹配同一 reviewer 后续"范围收窄" comment 的最终决定 |
| 6 | clamp 加 counter + Warn | ✅ 加过又按后续指示砍掉 counter | 只留 `Warn` 日志（`sumSpendUsd24h` 内），专用 Prometheus counter 已删除 |
| 7 | 加 per-model "tokens>0 且 cost==0" 计数器 | ❌ 未修复（按最新指示故意不做） | 曾加过 `TKXZeroCostNonzeroTokensTotal`，后被同一 reviewer 在"范围收窄" comment 里要求删除（冗余于保留的 zero-fallback 告警 + 免费活动期必然误触发 + 抓取放大问题） |
| 8 | 给 `UsdUnpricedChargesTotal{fallback="zero"}` 加告警 | ✅ 已修复 | `UsdChargesFallingBackToZeroPrice` 保留在本地 `deploy/monitoring/prometheus-alerts.yml`（生产 terraform 接入见 #20） |
| 9 | 设计文档记一句 `og_to_usd_rate` 会漂移 | ✅ 已修复 | 已有完整段落说明静态汇率、无过期机制、长期低报/高报风险 |
| 10 | 非阻塞：`units.MicroPerUSD` 复用替代硬编码 `1_000_000` | ✅ 已修复 | |
| 11 | 非阻塞：float64 例外在 `pkg/units/usd.go` 注明 | ✅ 已修复 | |
| 12 | 非阻塞：设计文档示例 `316.00`→`316`，注释"same numeric value" | ✅ 已修复 | |
| 13 | 非阻塞：`ClampsNegativeSpendToZero` 加 `math.Signbit` 断言 | ✅ 已修复 | |
| 14 | 非阻塞：`tkxModelBreakdownLimit` 文档提截断偏向（ORDER BY tokens DESC 导致偏向丢高成本行） | ✅ 已修复 | 上一轮发现"压成一句"时把这个具体结论删没了，只剩泛泛描述，已补回 |
| 15 | 非阻塞：`DimModel` 下 `total_cost_usd` 的集成测试断言 | ✅ 已修复 | 已用真实 MySQL（`make test-int`）跑通过确认 |
| 16 | "已核实为安全"部分（rollup 一致性、watermark dedup、精度、查询成本、`max_execution_time`） | ➖ 无需处理 | 逐条重新核对代码（`user_repository.go:2385` 附近、`:1027` 的 `sargableLogsWatermarkDedup`、DSN 层 `max_execution_time` 拼接逻辑），均属实，不是待办 |
| **HIGH — gross billed value 不是实收现金** |||
| 17 | 文档写明 gross billed（含 credit、含 deferred） | ✅ 已修复 | 设计文档 3 条 bullet + `types.go`/handler doc 均已说明 |
| 18 | 改口径只算 `deposit_used`（方案 2） | ➖ 有意不做 | 业务判断，文档已明确记录选择方案 1（如实披露口径）的理由 |
| 19 | 顺手把 credit 占比做成内部指标 | ❌ 未修复（按后续 comment 故意撤回） | 曾用 `router_billed_cost_by_source_total` + `ChargeUserAndLog`/`ChargeUsdAndLog` 热路径埋点实现，后被同一 reviewer 在"范围收窄" comment 里要求整体删除（改热路径控制流代价过大，数据本来就在 `usage_logs.credit_used/deposit_used/deferred_used` 里）。`billing.go`/`usd_billing.go`/`metrics.go` 已 revert 回 `b8c1ed6` 时的字节级原状（`git diff` 零差异） |
| **HIGH — 4 条告警放在本地文件，生产不生效** |||
| 20 | 搬到 `deploy/gcp/terraform/modules/monitoring/main.tf` | ❌ 未修复（按后续 comment 刻意延后） | 明确留给独立 PR；`git diff` 确认该 terraform 文件零改动。**Production gap 依然真实存在**，设计文档如实记录了这个延后决定 |
| 21 | 免费活动期误触发的坑 | ➖ 已随 #7 作废 | 对应告警和指标整个删除，坑不存在了 |
| 22 | severity / 静音语义的坑 | ➖ 已随 #7 作废 | 对应 critical 告警和指标整个删除 |
| 23 | 抓取放大问题（counter 应改 GaugeVec 或加免责声明） | ➖ 已随 #7 作废 | 对应指标整个删除 |
| **范围收窄建议** |||
| 24 | 告警 4→1，只留 `UsdChargesFallingBackToZeroPrice` | ✅ 已修复 | `router_usd_stats` 分组现在只有这 1 条规则 |
| 25 | `router_billed_cost_by_source_total` 全套删掉 | ✅ 已修复 | 同 #19 |
| 26 | "gross vs net" 叙述四处 → 压缩三处代码注释 + 设计文档留权威版 | ✅ 已修复 | handler / `types.go` / service 三处均已压成一句指回设计文档 |
| 27 | `tkxModelBreakdownLimit` 12 行压成一句 | ✅ 已修复（含本轮补回丢失的内容） | |
| 28 | malformed 分支注释压一行 + 删两个测试 | ✅ 已修复 | `TestBuildTKXUsageReport_MalformedTotalCostUsdTreatedAsZero`、`TestBuildTKXUsageReport_MixedSignRowsNetCorrectly` 均已删除 |
| 29 | 明确不建议砍的 5 项（flag / 集成测试 / changelog 修正 / MicroPerUSD 等 / 口径说明） | ✅ 均保留 | 逐项 grep 确认未被误删 |

## 汇总

- **✅ 已修复**：20 项
- **➖ 有意不做 / 无需处理**：4 项（改口径方案 2、"已核实安全"部分、2 项随其他项作废）
- **⚠️ 按同一 reviewer 后续 comment 的最终决定处理**（非最初字面建议，但匹配最新指示）：1 项（malformed 分支）
- **❌ 明确未修复**：
  - 3 项因后续"范围收窄" comment 明确要求撤回而未做（per-model 计数器、credit 占比热路径指标、以及随之作废的 2 个坑）
  - **1 项刻意延后、production gap 依然真实存在**：4 条告警搬进生产 terraform（`deploy/gcp/terraform/modules/monitoring/main.tf`），留给独立 PR，mainnet 上目前没有任何 tkx-usage 相关的可评估告警

## 已知遗留（不在本次改动范围内，需要后续独立 PR 跟进）

1. `UsdChargesFallingBackToZeroPrice` 告警的生产（GCP Managed Prometheus）接入
2. 若业务判定 `spend_usd_24h` 需要是"可对账的实收营收"而非"gross billed volume"，需要改 `sumSpendUsd24h` 口径为只统计 `deposit_used`（+/- `deferred_used`），并新增 repo 层改动 + MySQL 集成测试
