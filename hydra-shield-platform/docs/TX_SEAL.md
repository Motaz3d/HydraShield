# TX Authenticity Seal

Every report and digital product issued by the Talaix TX engine carries a
branded authenticity seal so anyone can verify it was genuinely issued by the
platform.

## Seal format

`TX-XXXX-XXXX-XXXX` — literal `TX-` prefix + 16 uppercase hex characters
grouped as 4-4-4.

Regex: `^TX-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$`

## Computation

```text
HMAC-SHA256(key, msg).hexdigest()[:16].upper()
msg = "talaix-tx-seal|" + canonical_json(payload)
```

`canonical_json` is the same stable serialisation used by
`src.climate.evidence.content_hash`: `json.dumps(..., sort_keys=True,
separators=(",", ":"), default=str)`.

The key source mirrors `src.dashboard.accounts._server_key`:

* Use the `HYDRASHIELD_SECRET_KEY` environment variable when set.
* In development, fall back to a SHA-256 digest of
  `hydrashield-dev-token-key|<hostname>|<home>`.  Codes generated without the
  env key will not verify across machines, just like session tokens.

The platform never logs the secret key or full HMAC digests.

## Verification modes

### 1. Registry lookup — documents

At issuance, every document product records its seal in the `tx_seals` table
of the shared `VerificationStore` SQLite database:

| column       | type | note                                    |
|--------------|------|-----------------------------------------|
| `code`       | TEXT | primary key                             |
| `kind`       | TEXT | product kind, e.g. `verification`       |
| `ref_id`     | TEXT | short reference id                      |
| `meta_json`  | TEXT | small metadata blob                     |
| `created_at` | TEXT | UTC ISO-8601 with `Z` suffix            |

`GET /api/v2/verify/<code>` returns:

```json
{
  "valid": true,
  "code": "TX-...",
  "kind": "verification",
  "ref_id": "...",
  "issued_at": "2026-09-04T10:00:00Z",
  "engine": "TX"
}
```

Unknown codes return `{valid: false}` with HTTP 200 (it is a check, not an
error).

### 2. Stateless recomputation — JSON payloads

For high-volume JSON analysis results, the seal is not stored.  Callers can
verify statelessly:

```bash
POST /api/v2/verify
{"payload": <original object>, "code": "TX-..."}
```

Response:

```json
{"valid": true, "code": "TX-..."}
```

This mode covers `TxResult` JSON envelopes and any future product that does
not use the registry.

## Where seals appear

* PDF footers: `verify TX-XXXX-XXXX-XXXX`.
* JSON responses: `authenticity.code` inside document payloads and
  `TxResult.to_dict()`.
* Wildfire reports: `src.dashboard.report.build_report_pdf`.
* Product engines: verification, insurance, forensics, sustainability,
  supply-chain, press, report-builder.

## Honest scope

The seal proves that a document or payload was issued by the Talaix TX engine.
It does not prove that every claim inside is true.  Evidence status,
uncertainty, model limitations and declared data gaps remain part of the
product content itself (see `EVIDENCE_ARCHITECTURE.md`).
