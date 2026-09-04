# Talaix — Visual Report Builder

The Report Builder gives users two ways to produce an evidence report:

1. **Automatic** — one click to the existing product PDF endpoints
   (`/api/v2/verification/report`, `/api/v2/insurance/profile/report`,
   `/api/v2/sustainability/report/pdf`).
2. **Interactive** — a structured draft is generated from the same engine
   payloads, every section explains why it exists, the user can edit/reorder
   sections, and the exported PDF honestly marks any user edits.

## Concept

The interactive builder is designed around the honesty contract:

- All draft text is **template-composed deterministically** from the real
  engine payloads (numbers, levels, claim statuses, evidence counts, sources,
  disclaimers).
- **No AI generation** and **no invented prose**. The language is rigid
  scaffolding filled with payload values.
- Every section carries a `why` field: a one-sentence account of the payload
  path(s) that produced it.
- Any section the user edits is flagged `edited: true`; the PDF layer renders
  an "[edited by user]" marker and the metadata block declares the edit count.

This preserves the platform's evidence contract while giving users editorial
control over framing and emphasis.

## Section schema

A draft section returned by `POST /api/v2/report-builder/draft` looks like:

```json
{
  "id": "hazard-flood",
  "kind": "introduction" | "body" | "gaps" | "conclusion",
  "heading": "Riverine / pluvial flooding",
  "text": "...",
  "why": "Built from the flood hazard module result: level 'Low', claim status MODELLED, 2 evidence record(s).",
  "source_refs": ["flood", "flood:ev-123"],
  "edited": false,
  "ai_polished": false
}
```

Top-level draft:

```json
{
  "draft_id": "a1b2c3d4...",
  "kind": "verification",
  "title": "Physical Asset Verification — Clervaux",
  "generated_at": "2026-08-25T12:00:00Z",
  "engine_version": "1.0.0",
  "payload_id": "...",
  "disclaimer": "...",
  "sections": [...],
  "interconnection_note": "All sections describe the same underlying engine run...",
  "honesty_note": "Engine text is template-composed from the cited evidence only; edited sections are marked in the exported PDF."
}
```

## How text is composed

`src/climate/report_builder.py` calls the same engines used by the product
endpoints:

- `verification` → `verify_asset(lat, lon, name)`
- `insurance` → `build_risk_profile(lat, lon, name, radius_km)`
- `sustainability` → `build_sustainability_evidence(company, assets)`

Each mapper turns the payload into a fixed section order:

- **Introduction** — asset/company identity, scope, engine version, disclaimer.
- **Body sections** — one per hazard/peril/site, using only payload-derived
  values (level label, claim status, confidence, evidence count, event count,
  limitations).
- **Gaps section** — declared gaps flattened, or an honest "none declared".
- **Conclusion** — summary counts, honesty contract, monitoring hint.

The `draft_id` is a content hash of the kind, params and section texts, so the
same inputs always produce the same draft identity.

## Edited-marking rule

- `edited` starts as `false` for every engine-generated section.
- The frontend sets `edited: true` on the first user edit to a section's
  heading or body.
- `prepare_sections()` in the backend validates the submitted sections and
  counts `edited: true` entries.
- `build_custom_pdf()` renders each edited section with an "[edited by user]"
  marker and includes the edit count in the metadata table.
- The final "Composition & honesty" paragraph states:
  "N of M sections were edited by the user. Engine-generated text is
  template-composed from the cited evidence only; user-edited text is the
  user's own."

## AI prose polish

The Report Builder can optionally polish user-edited section prose through a
server-side Kimi API gateway. The feature is disabled when `KIMI_API_KEY` is
unset; in that state the polish endpoint returns `503` and the UI shows a
clear "unavailable" message.

- Polishing is available per-section from the section editor. The button is
  enabled only when the section body is non-empty.
- The server sends the section heading and text to the gateway with the
  `polish` task kind. Routing is provider-aware and cheap-first:
  - `KIMI_PROVIDER=code` (default, Kimi Code membership API at
    `api.kimi.com/coding/v1`): cheap tier `kimi-for-coding`, strong tier
    `k3-256k` (used only by `deep_analysis`).
  - `KIMI_PROVIDER=platform` (pay-as-you-go Kimi Platform at
    `api.moonshot.cn/v1`; use `platform-international` for
    `api.moonshot.ai/v1`): cheap tier `moonshot-v1-8k`, strong tier
    `kimi-k2-0711-preview`.
  - `KIMI_BASE_URL`, `KIMI_MODEL_CHEAP` and `KIMI_MODEL_STRONG` override the
    endpoint and model ids when a provider introduces new ids — callers never
    pick models ad hoc.
- The system prompt instructs the model to improve clarity and grammar only:
  it must not invent facts, numbers, hazard labels, source references, or
  conclusions absent from the user's text.
- A successfully polished section is returned to the frontend, which marks it
  `edited: true` and `ai_polished: true`.
- The exported PDF renders an `[AI-polished]` marker below the section text,
  in addition to any `[edited by user]` marker, and the metadata block
  declares the count of AI-polished sections.
- Daily call volume is capped by `AI_DAILY_CALL_CAP` (default: 50). Once the
  cap is reached the gateway refuses further calls until midnight UTC.
- The API key is read from the environment only and is never logged or
  returned in error responses.

## API reference

Both endpoints require a registered session and are rate-limited to 6/min per
client IP.

- `POST /api/v2/report-builder/draft`
  - Body: `{ "kind": "verification"|"insurance"|"sustainability", "params": {...} }`
  - Returns: `{ "draft": {...} }`
  - Errors: 400 for invalid kind/params, 502 for engine failure.

- `POST /api/v2/report-builder/polish`
  - Body: `{ "heading": "...", "text": "..." }`
  - Returns: `{ "text": "..." }`
  - Errors: 400 for missing/oversized text, 401/403 for unregistered sessions,
    429 for rate limit, 503 when AI is not configured or the daily cap is
    reached, 502 for upstream failure.

- `POST /api/v2/report-builder/pdf`
  - Body: `{ "title": "...", "sections": [...], "draft_id": "...", "generated_at": "...", "kind": "...", "engine_version": "...", "honesty_note": "...", "disclaimer": "..." }`
  - Returns: PDF bytes (`application/pdf`).
  - Errors: 400 for malformed sections, 503 if reportlab is unavailable, 502
    for PDF failure.

## Frontend

The builder UI lives inside the Reports portal — `website/reports.html`
(the `#builder` section; legacy `report-builder.html` redirects there) —
with `website/js/report-builder.js` implementing:

- Mode choice cards (automatic vs interactive).
- Product-specific setup forms:
  - Verification / Insurance: location input (resolved via `HS.resolveLocation`)
    plus radius for insurance.
  - Sustainability: company fields + site textarea parser (same format as
    `sustainability.js`).
- Section editor with editable heading/text, "Why this section?" expander,
  up/down reorder, remove (body sections only), edited chip, and a per-section
  "Polish with AI" button.
- Export button with blob download and an edit-count summary line.

## Roadmap (out of scope for this phase)

- Per-section regeneration from updated engine inputs.
- Additional report kinds (forensics, supply-chain evidence packs).
