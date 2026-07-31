# 0g-serving-broker: feat/kling-vidu-integration → main

## Summary

- Add **Kling** (Aliyun/DashScope async text-to-image) as a new `imagetranslator` sidecar, following the existing `videotranslator` DashScope/MiniMax pattern (native client → pure translate layer → gin handler).
- Add **Vidu** (Aliyun/DashScope start/end-frame-to-video) as a new provider inside the existing `videotranslator` sidecar, alongside DashScope and MiniMax.
- Extract a shared `handler.Provider` interface out of `videotranslator`'s handler package so DashScope, MiniMax, and Vidu all serve the OpenAI Video API surface through one generic handler, instead of a third hand-copied implementation.
- Register both applets in `api/main.go` (`0g-kling-image-translator`, `0g-vidu-video-translator`).

## Design notes worth flagging to reviewers

- **Kling is synchronous from the broker's perspective, Vidu is not.** Kling's vendor API is async-only (submit → poll → fetch), but the broker's existing image-generation contract is synchronous end-to-end. Since there's no deferred-poll billing scheduler for images (unlike video), `CreateImage` polls Kling to a terminal state internally, inside one HTTP handler call, before ever responding. Vidu instead mirrors DashScope/MiniMax exactly: `CreateVideo` returns "queued" immediately, and the caller polls `GET /videos/{id}` / fetches `GET /videos/{id}/content` separately.
- **Vidu billing precedence**: the vendor's actually-billed `usage.duration` is read before the client-echoed `usage.output_video_duration` (clip length, can diverge) — mirrors the same precedence bug class MiniMax's integration already guards against.
- **Reference-image handling**: Kling and Vidu both allowlist `http(s)://` only for reference images (no `data:` URI support, unlike MiniMax) — a client-uploaded file that degrades to a `data:` URI is dropped rather than forwarded to a vendor field that doesn't accept it.
- Neither sidecar stores or reads the vendor API key; the broker's existing `additionalSecret` config mechanism injects the `Authorization` header on every outbound call, matching the DashScope/MiniMax precedent exactly.

## Testing

- `go test ./videotranslator/... ./imagetranslator/...` — all packages pass, including new unit tests for both vendors' translate/handler layers.
- Manually verified both sidecars end-to-end as real running processes against a mock DashScope-shaped vendor server (real HTTP, not just in-process test harness): Kling's full create→poll→fetch→base64 pipeline, and Vidu's create/validation paths, including the specific request-validation edge cases (out-of-range `n`, malformed multipart fields, missing/invalid reference frames).

## Not in this PR

- Real DashScope/Vidu API keys and on-chain provider registration — operational steps outside this repo's git history (broker's own `config.yaml` holding `additionalSecret` is gitignored by design).
