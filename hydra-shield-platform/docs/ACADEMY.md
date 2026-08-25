# Talaix Academy

Talaix Academy is a brand amplifier and sales funnel: short, evidence-literate
courses that teach financial professionals how to read climate risk and use the
platform's evidence layers. The pilot course is open to the public; grading,
certificates and progress tracking require a free registered account.

## Purpose

- Teach physical climate risk, EU sustainability frameworks and evidence
  literacy in plain language.
- Drive hands-on use of the Green Finance, Sustainability, Insurance, Supply
  Chain and Forensics tools.
- Issue a **Certificate of Completion** that honestly states what it is and is
  not.

## Pilot course

`climate-risk-finance` — *Climate Risk Assessment for Financial Institutions*

Audience: bank, insurance and investor staff facing CSRD, EBA and EIOPA climate
requirements.

Modules:

1. **Foundations** — physical vs transition risk; acute vs chronic hazards;
   TCFD → IFRS S2; supervisory expectations (EBA, ECB, EIOPA).
2. **EU framework map** — EU Taxonomy + DNSH; SFDR Article 6/8/9 as
   disclosure categories; CSRD + ESRS + double materiality; EBA Pillar 3 ESG
   and the Green Asset Ratio; EU Green Bond Regulation and ESMA-registered
   external reviewers.
3. **Evidence literacy** — claim-status vocabulary; confidence and screening
   indicators; why "data unavailable" is a legitimate answer; greenwashing
   cases (DWS €25M Frankfurt prosecutors fine in 2025; BNY Mellon $1.5M SEC
   settlement in 2022); physical evidence as a counter-layer.
4. **Hands-on: verify a financed asset** — EU Taxonomy Appendix A hazards;
   walking the Green Finance DNSH checklist; declared gaps; what the report is
   not (not an SPO, not an ESMA-registered review).
5. **Hands-on: read disclosures and risk profiles** — ESRS coverage map;
   Insurance risk profile structure; lender vs insurer perspective.
6. **Final assessment** — recap + 8-question quiz.

## Grading and passing threshold

Each module quiz is graded server-side. The passing threshold is **70%**,
computed as `ceil(0.7 * n)` where `n` is the number of questions:

- 3-question modules: 3/3 required to pass.
- 4-question modules: 3/4 required to pass.
- 8-question final assessment: 6/8 required to pass.

The platform stores the **best** score per module across attempts.

## Certificate of Completion

When all modules (including the final assessment) are passed, the user can
issue a Certificate of Completion.

The certificate PDF and public verify endpoint state clearly:

> "This certificate attests completion of the Talaix Academy pilot course. It
> is not an accredited academic qualification and not a professional
> certification."

A university partnership is **planned**, not claimed.

## Public verification

Anyone can verify a certificate at
`GET /api/v2/academy/certificates/<certificate_id>/verify`. A valid response
returns the recipient name, course, score and issue date. An invalid ID returns
`valid: false` with a 404.

## Config file formats

Courses live in `config/academy_course.json`:

```json
{
  "courses": [
    {
      "id": "course-id",
      "title": "...",
      "audience": "...",
      "description": "...",
      "certificate_note": "...",
      "modules": [
        {
          "id": "module-id",
          "title": "...",
          "minutes": 10,
          "summary": "...",
          "sections": [{"heading": "...", "body": "..."}],
          "key_terms": ["eu_taxonomy"],
          "try_it": {"label": "...", "href": "page.html"},
          "quiz": [
            {
              "question": "...",
              "options": ["...", "...", "...", "..."],
              "correct_index": 0,
              "explanation": "..."
            }
          ]
        }
      ]
    }
  ]
}
```

Glossary terms live in `config/academy_glossary.json`:

```json
{
  "terms": [
    {
      "id": "term-id",
      "term": "...",
      "short": "...",
      "long": "...",
      "related": ["other-term"],
      "module": "module-id",
      "platform_link": "page.html"
    }
  ]
}
```

`correct_index` and `explanation` are stripped from all public course endpoints.

## API

- `GET /api/v2/academy/courses` — public course catalogue.
- `GET /api/v2/academy/courses/<course_id>` — public course content (answers
  stripped).
- `GET /api/v2/academy/glossary` — all terms.
- `GET /api/v2/academy/glossary/<term_id>` — one term.
- `POST /api/v2/academy/progress` — registered+, grade and persist best score.
- `GET /api/v2/academy/progress?course_id=` — registered+, my progress.
- `POST /api/v2/academy/certificate` — registered+, issue Certificate of
  Completion (idempotent).
- `GET /api/v2/academy/certificate/pdf?course_id=` — registered+, download
  certificate PDF.
- `GET /api/v2/academy/certificates/<id>/verify` — public authenticity check.

## Roadmap

- More courses aligned to each business line (Insurance, Supply Chain,
  Forensics).
- University partnership and academic accreditation where appropriate.
- Exploration of CPD-point recognition — stated as a plan, not a claim.
