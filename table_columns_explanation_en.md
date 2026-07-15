Note

This document is based on the 0g-router repo, main branch, commit fb40237 (fast-forwarded to the latest origin/main, which merged PR #574 "USD settlement mode Phase 1" plus the follow-up USD/Stripe billing commits). Every column's meaning has been verified against the current code, and the sample data below has been checked arithmetically against the invariants the code implies.

================================================================
Table: user_balances
================================================================

user_address
  Meaning: Primary key, lower-cased EVM wallet address. The row is lazily created on first login / first deposit.
  Code evidence: backend/internal/model/models.go:7-31; user_repository.go

deposit_balance
  Meaning: The user's on-chain-funded, Router-tracked spendable balance (wei string, varchar(100)). Effective available balance = deposit_balance - pending_charge.
  Code evidence: Credited by ProcessDepositAndSettle; debited by DeductAvailableAndDefer (both in user_repository.go)

credit_balance
  Meaning: Router-granted, non-on-chain credit (e.g. welcome bonus). Consumed before deposit_balance on every charge. Credit spend never touches total_consumed / total_settled / pending_charge -- those three track on-chain money only.
  Code evidence: user_repository.go; isolation rule documented in billing.go

total_consumed
  Meaning: Cumulative, monotonically-increasing on-chain-side consumption (depositUsed + deferred, deliberately excluding credit spend).
  Code evidence: IncrementTotalConsumedWithTx (user_repository.go), called from billing.go

total_settled
  Meaning: Cumulative, monotonically-increasing amount actually confirmed settled on-chain via the RouterPayment contract's batchSettle / Settled event.
  Code evidence: MarkSettleConfirmedAndCredit / ProcessSettledEvent (user_repository.go); de-duplicated via the settle_logs pending/confirmed status

pending_charge
  Meaning: Deferred/unbacked charge (wei) -- cost billed to the user that exceeded credit_balance + deposit_balance at charge time. Paid down first whenever a new deposit lands. While pending_charge > 0, every new request is forced onto the deferred-charge path.
  Code evidence: Increased by DeductAvailableAndDefer; decreased by ProcessDepositAndSettle (both user_repository.go)

deposit_pull_active
  Meaning: Boolean; set to true exactly once, on the account's first successful non-zero charge, and never reset. Gates whether PaymentWorker manages/tops-up this user's balance.
  Code evidence: MarkDepositPullActiveWithTx, called from billing.go

pl_pull_pending_at
  Meaning: Nullable timestamp -- a de-duplication lock marking "PaymentWorker just issued a Payment-Layer deposit-pull request for this user, still awaiting confirmation." Has a 5-minute TTL fallback so a lost request can't pin a user forever.
  Code evidence: MarkPLPullPending / ClearPLPullPending (user_repository.go); TTL logic in payment_worker.go

refund_pending
  Meaning: Boolean; when true, blocks all inference for the account (HTTP 423) and excludes it from settlement / PaymentWorker pull / metrics aggregation. There is no automatic setter in the code -- this is set manually by an operator as part of an off-chain refund process.
  Code evidence: handler/inference.go; docs/payment-layer-design.md

created_at / updated_at
  Meaning: Standard GORM timestamps; updated_at is also explicitly stamped NOW() in every hand-written SQL UPDATE.
  Code evidence: models.go:24-25

settlement_mode
  Meaning: Which billing ledger the account currently bills against: "0g" (default, the existing on-chain wei path) or "usd" (the parallel, off-chain prepaid usd_balances ledger). This is a freely reversible switch that moves no money. It is only ever consulted when the features.usd_billing flag is on -- while the flag is off, SettlementMode() short-circuits to "0g" without even reading the database.
  Code evidence: Field definition models.go:24-30,41-44; flag-gated resolver service/usd_billing.go (SettlementMode); setter usd_billing.go (SetSettlementMode) exposed via POST /account/settlement-mode (handler/account.go, route only registered when features.usd_billing.Enabled, see router/router.go); design doc docs/usd-billing-design.md section 2: "can be flipped at any time... not a one-time, irreversible identity"

================================================================
Table: usage_daily_summaries
================================================================

Nature of the table: a permanent, retention-free daily rollup, batch-aggregated (via AggregateUsageLogsToDate) from the retention-bounded (default 90-day) usage_logs table -- it is NOT written directly at charge time. Unique key (idx_daily_unique): (user_address, date, canonical_id, api_key_id, partner_id, trust_mode, currency).

id
  Meaning: Auto-increment surrogate primary key; carries no business meaning.
  Code evidence: models.go:421

user_address
  Meaning: Wallet address (lower-cased); 1st component of the unique key.
  Code evidence: models.go:422

date
  Meaning: The UTC calendar day the rollup covers (DATE(created_at) from the source rows), not the write time; 2nd component of the unique key.
  Code evidence: AggregateUsageLogsToDate (user_repository.go)

canonical_id
  Meaning: The actual GROUP BY key -- the router-registry-resolved, provider-agnostic model id. Empty string is the "unmapped" sentinel. 3rd component of the unique key.
  Code evidence: models.go:424-439

model_id
  Meaning: A legacy dual-emit mirror of canonical_id, written with the exact same value, kept only so old API clients reading the old field name still get correct data; slated for removal.
  Code evidence: AggregateUsageLogsToDate's INSERT ... SELECT ... canonical_id AS model_id

api_key_id
  Meaning: The api_keys.key_id (UUID) that authenticated the request, or empty string for JWT/session auth. 4th component of the unique key.
  Code evidence: models.go:441

partner_id
  Meaning: The self-reported X-0G-Source-Id header value, but only kept if it matches a registered, active partner -- otherwise collapsed to ''. 5th component of the unique key.
  Code evidence: service/partner_attribution.go

trust_mode
  Meaning: The trust tier of the provider that actually served the request (standard / verified / private, floor semantics). 6th component of the unique key.
  Code evidence: pkg/trustmode/trustmode.go

request_count
  Meaning: COUNT(*) of usage_logs rows aggregated into that bucket for the day, including zero-cost/free-event requests.
  Code evidence: AggregateUsageLogsToDate

input_tokens / output_tokens
  Meaning: Daily SUM. input_tokens already includes the cache subsets below -- they are not additional.
  Code evidence: AggregateUsageLogsToDate

cached_tokens
  Meaning: The cache-read (hit) subset of input_tokens, from Anthropic's cache_read_input_tokens, billed at a discount.
  Code evidence: pkg/inference/anthropic_handler.go

cache_write_tokens
  Meaning: The cache-write (default/5-minute-TTL) subset of input_tokens.
  Code evidence: pkg/inference/anthropic_handler.go

cache_write_1h_tokens
  Meaning: The 1-hour-TTL portion of cache-write tokens, disjoint from cache_write_tokens.
  Code evidence: pkg/inference/anthropic_handler.go

cost
  Meaning: Total charge for the bucket. When currency='0g', unit is wei; when currency='usd', unit is micro-USD (USD x 1e6).
  Code evidence: service/usd_billing.go (scaleToMicroCeil, rounds up so it never under-bills)

credit_used
  Meaning: Portion of cost paid from credit (0g mode: credit_balance; usd mode: usd_balances.credit).
  Code evidence: user_repository.go / usd_repository.go (DeductUsd)

deposit_used
  Meaning: Portion of cost paid from real, revenue-bearing funds (0g mode: deposit_balance; usd mode: usd_balances.balance).
  Code evidence: user_repository.go / usd_repository.go (DeductUsd)

deferred_used
  Meaning: Portion of cost that couldn't be covered and was recorded as owed. In USD mode this is always hard-coded to "0" -- USD is a prepaid model with no deferred-charge concept; only 0g-mode rows can be non-zero.
  Code evidence: service/usd_billing.go (ChargeUsdAndLog, literal DeferredUsed: "0"). Invariant credit_used + deposit_used + deferred_used = cost holds in both modes (usd mode: credit_used + balance_used == cost, per usd_repository.go's DeductUsd docstring)

created_at
  Meaning: Write/upsert time of the summary row; not the business date.
  Code evidence: models.go:473

currency
  Meaning: The unit of cost / the three "*_used" fields: "0g" (wei, default) or "usd" (micro-USD). Now the 7th component of the unique key -- AggregateUsageLogsToDate's rollup SQL actually GROUP BYs on it, so wei and micro-USD rows are never summed together.
  Code evidence: Field def models.go:577-585; GROUP BY logic in AggregateUsageLogsToDate (user_repository.go); migration 016 (add_currency_to_daily_unique, repository/migrations.go) folded currency into idx_daily_unique

