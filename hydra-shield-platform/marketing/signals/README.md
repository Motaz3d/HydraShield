# Commercial signals ledger

One JSON file per observed commercial signal, following `schema.json`.
**Empty by design** — a signal is committed only after its source URL has
been live-checked. See `docs/COMMERCIAL_INTELLIGENCE.md` for the radar
architecture and the activity-classification rule (qualitative evidence →
`activity_level` LOW/MEDIUM/HIGH, never a spend figure).
