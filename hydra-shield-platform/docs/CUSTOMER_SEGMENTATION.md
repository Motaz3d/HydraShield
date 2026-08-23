# Talaix — Customer Segmentation

**Status:** implemented (Phase C). The data source of record is
`marketing/segments/segments.json`; this document is the model and
reading guide.

## Model

Each segment declares, in machine-readable form:

| Field | Purpose |
|---|---|
| `pain_points` | the climate-driven problems the segment plausibly faces |
| `relevant_hazards` | which of the six hazards matter most |
| `capabilities` | the *real* platform capabilities that address the pain |
| `decision_maker_roles` | roles to address (roles, not invented names) |
| `content_topics` | what we publish for this segment |
| `offer` / `cta` | the concrete first step we propose |
| `outreach_style` | tone register for drafts |
| `evidence_requirements` | what proof this segment expects before trusting us |

Segments: insurance · real estate · construction · banking · investment ·
asset management · energy · logistics · ports · agriculture ·
manufacturing · tourism · telecom · data centers · municipalities ·
governments · research centers · universities · NGOs.

## Usage rules

1. **Drafts must name their segment** and follow its style + evidence bar
   (`docs/MARKETING_INTELLIGENCE.md` §3).
2. **Capabilities referenced must exist.** If a draft wants a capability
   the platform lacks, that is a product finding — record it in
   `marketing/analytics/`, never paper over it in copy.
3. **Pain points are hypotheses until validated** by real conversations;
   validate through pilot conversations and record outcomes in the lead's
   `interactions`.
4. Segment changes are commits: evolving a segment definition is a
   reviewed edit to `segments.json`, so learning is versioned.

## Where segments meet the product

The product ladder (docs/PRODUCT_STORY.md §7) maps to segments:
municipalities/governments/NGOs/universities start from the free tier and
monitoring; insurance/banking/investment/real-estate/energy/ports start
from analysis + reports and convert at monitoring, API and multi-location
needs. Conversion signals come from product analytics (Phase B) — e.g.
which pages and hazards precede `account_created`.
