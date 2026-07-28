# `spend_usd_24h` 精确计算链路 — 精确到库/表/行列

基于源码逐层核对（不是复述文档，是重新读代码确认的）。

## 第0步：请求进来，路由到哪个handler

`GET /tkx-usage.json` 请求进来，`internal/router/router.go` 里注册的路由（前提：`tkx_usage.enabled=true`）把它转给 `handler.GetTKXUsageReport`（`internal/handler/tkx_usage.go`）。

## 第1步：Handler → Service，没有任何数据库操作

`handler.GetTKXUsageReport` 直接调用 `svc.GetTKXUsageReport()`，这个方法在 `internal/service/tkx_usage.go` 里，逻辑很薄：

```go
func (s *Services) GetTKXUsageReport() (*TKXUsageReport, error) {
    return s.buildTKXUsageReport(time.Now().UTC())
}
```

`buildTKXUsageReport` 先算出"昨天"这个UTC自然日的边界（`yesterday := dateOnlyUTC(now.AddDate(0,0,-1))`），然后调用仓储层：

```go
rows, _, err := s.tkxUsageRepo.GetUsageBreakdown(repository.DimModel, &yesterday, &yesterday, "", tkxModelBreakdownLimit, 0)
```

真正碰数据库的，就是这一行。

## 第2步：`GetUsageBreakdown` 到底查了哪个库、哪张表、哪些列

代码在 `internal/repository/user_repository.go:1466`。它实际发出的SQL，本质是一个UNION，**读两张表**：

### 表1：`usage_daily_summaries`（已经按天永久归档的旧数据）

```sql
SELECT
    COALESCE(NULLIF(canonical_id, ''), model_id) AS k,   -- 按模型分组的key
    SUM(request_count)              AS rc,
    SUM(input_tokens + output_tokens) AS tt,
    SUM(input_tokens)               AS it,
    SUM(output_tokens)              AS ot,
    ...(native cost)...              AS c,
    SUM(CAST(cost_usd_micro AS DECIMAL(65,0))) AS cu     -- ← 这一列就是美元花费的来源
FROM usage_daily_summaries
WHERE date >= '2026-07-27' AND date <= '2026-07-27'
GROUP BY COALESCE(NULLIF(canonical_id, ''), model_id)
```

### 表2：`usage_logs`（还没被归档、当天新写入的原始逐笔请求记录）

```sql
SELECT
    COALESCE(NULLIF(canonical_id, ''), model_id) AS k,
    COUNT(*)                         AS rc,
    SUM(input_tokens + output_tokens) AS tt,
    SUM(input_tokens)                AS it,
    SUM(output_tokens)                AS ot,
    ...(native cost)...               AS c,
    SUM(CAST(cost_usd_micro AS DECIMAL(65,0))) AS cu     -- ← 同一列，同一逻辑
FROM usage_logs
WHERE created_at >= '2026-07-27' AND created_at < '2026-07-28'
  AND created_at >= (usage_daily_summaries里MAX(date) + 1天)   -- 水位线去重，防止跟表1重复计数
GROUP BY COALESCE(NULLIF(canonical_id, ''), model_id)
```

两个分支`UNION ALL`起来之后，外层再按`k`（模型）重新`GROUP BY`一次、汇总，得到最终每个模型一行：

```sql
SELECT k,
    COALESCE(SUM(rc), 0)  AS requests,
    COALESCE(SUM(tt), 0)  AS tokens,
    ...
    COALESCE(CAST(SUM(cu) AS CHAR), '0') AS total_cost_usd   -- ← 这就是返回给Go代码的字段
FROM (上面两个UNION的结果) AS u
GROUP BY k
ORDER BY tokens DESC, k ASC
LIMIT 10000 OFFSET 0
```

**所以精确地说**：`total_cost_usd`这个数字，来自`usage_logs.cost_usd_micro`（未归档的当天新记录）和`usage_daily_summaries.cost_usd_micro`（已归档的历史记录）这两列，逐行`CAST(... AS DECIMAL(65,0))`再`SUM`，按模型分组。这一步是**读**，不做任何计算——所有金额早就在写入这两张表的时候就已经算好了。

## 第3步：`usage_logs.cost_usd_micro` 这一列，是什么时候、怎么写进去的

这才是真正"算钱"的地方，跟`GetUsageBreakdown`完全无关，发生在**用户实际调用API、拿到provider返回结果的那一刻**（`internal/service/billing.go`，`ChargeUserAndLog`函数）：

```go
costUsdMicro := s.CostUsdMicroFor0G(modelID, providerAddress, cost, inputTokens, outputTokens, cachedTokens, cacheWriteTokens, cacheWrite1hTokens)
```

`CostUsdMicroFor0G`（`internal/service/usd_billing.go:498`）内部：

1. 查这个模型的`pricing_usd`（`providers`表里的一列，就是`/v1/models`接口返回的那个价格）；
2. 用`CalculateCostUSDMicro`（同文件`:250`），把`inputTokens`/`outputTokens`/`cachedTokens`这几个真实token数，按当时的单价（含缓存折扣逻辑）算出美元花费；
3. 算出来的结果，连同这次请求的`input_tokens`/`output_tokens`/`cached_tokens`，一起`INSERT`进`usage_logs`表的这一行，`cost_usd_micro`这一列就是这个结果。

到了凌晨02:00 UTC，一个归档任务（`AggregateUsageLogsToDate`）会把前一天`usage_logs`里的行按`(canonical_id, model_id, ...)`分组`SUM`一遍，写进`usage_daily_summaries`表，`cost_usd_micro`这一列就是`usage_logs.cost_usd_micro`的汇总值（这里也做了`SUM(CAST(cost_usd_micro AS DECIMAL(65,0)))`）。这一步之后，第2步查询到的就是这张归档表，而不再是原始的`usage_logs`。

## 第4步：Service层把每个模型的`total_cost_usd`加总成一个数

回到`internal/service/tkx_usage.go`的`sumSpendUsd24h`函数：拿到第2步返回的、每个模型一行的`TotalCostUsd`（十进制字符串，单位是百万分之一美元），用`big.Int`逐行`Add`累加，最后用`big.Rat.FloatString(2)`四舍五入到分，转成`float64`放进JSON的`spend_usd_24h`字段。

## 一句话总结整条链路

```
用户调API
  → ChargeUserAndLog（billing.go）当场按真实token数+当时单价+缓存折扣算出美元花费
  → 写进 usage_logs.cost_usd_micro（这一笔请求的记录）
      │
      ▼ (凌晨02:00 UTC 归档任务)
  usage_daily_summaries.cost_usd_micro（按天汇总）
      │
      ▼ (GET /tkx-usage.json 请求进来)
  GetUsageBreakdown 同时UNION查 usage_logs（今天还没归档的部分）+ usage_daily_summaries（已归档部分）
  → 按模型分组，SUM(cost_usd_micro) 得到 total_cost_usd
      │
      ▼
  sumSpendUsd24h 把所有模型的 total_cost_usd 再加一遍
      │
      ▼
  spend_usd_24h（四舍五入到分）
```
