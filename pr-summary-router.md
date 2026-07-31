# 0g-router: feat/kling-vidu-integration → main

> **Depends on** https://github.com/0gfoundation/0g-router/pull/657 (the `video-generation-routing`
> infrastructure). That PR is merged into this branch already, so this diff also contains its commits —
> Vidu's registry entries/gating need that work to exist (the `video-generation` service type, async
> routing, billing) before they mean anything. Please review/merge #657 first; the commits specific to
> this PR are `c19c13f` and `3f2ba94` on top of it.

## Summary

- Register Kling (`kling/kling-v3-image-generation`, text-to-image) and four Vidu variants
  (`vidu/vidu{q3,q2}-{pro,turbo}_start-end2video`, video-generation) as canonical models.
- Add a Kling-specific Cloud Run flag (`features.kling_image_generation`) that gates a model-ID-prefix
  filter — Kling shares the already-live, unflagged `text-to-image` service type with other providers
  (e.g. `z-image-turbo`), so it can't use a whole-service-type flag the way video-generation does.
  Applied identically at routing, every catalog listing, **and the pinned-address path**, so the flag
  can't be bypassed by pinning a known provider address directly.
- Add a second, Vidu-specific flag (`features.vidu_video_generation`) on top of the shared
  `features.video_generation` flag from #657. On-chain provider registration is permissionless, and
  `video_generation` is already `true` in staging — so merging Vidu's registry entries there could expose
  it to real traffic before validation completes. This flag defaults `false` in every environment,
  including staging, and mirrors the Kling gate's mechanism exactly.
- Add a per-user in-flight job cap for Kling (`CountInFlightAsyncJobsByModelPrefix`,
  `KlingInFlightReserve`/`Release`), mirroring the existing video cap but scoped to Kling's model-ID
  prefix (resolved to the canonical id, so a future Kling alias can't silently escape it) so other
  text-to-image providers are unaffected.
- Full terraform wiring for both new flags — root variable, compute-module pass-through, both Cloud Run
  services (`backend` + `worker`), both `.tfvars` environments.

## Testing

- `go test ./...` — all packages pass, including new unit + SQLite-backed tests for both gates (name,
  empty-policy, filter-chain placement, pinned-path bypass) and the in-flight cap (scoping, alias
  resolution).
- A `//go:build integration` test (`TestCountInFlightAsyncJobsByModelPrefix_UsesLeadingColumnIndex`)
  asserts the new query hits the existing `idx_async_user_submitted` index via `EXPLAIN` — requires a
  real MySQL testcontainer, not run in this environment; flagged here for the reviewer to run
  (`make test-int`) rather than claimed as verified.

## Not in this PR

- Flipping either flag on anywhere — both stay `false` until 1-testnet validation (Kling) / staging
  sign-off (Vidu) completes, per this repo's Deploy≠Release discipline.
