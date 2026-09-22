# Corpus Ingest Report

Snapshot: `01a0c2a9-e900-7852-b00b-ae99219ec69a`
Parser: `continuous_para/1.0+annex_table/1.0`

## DL2025 — Reserve Bank of India (Digital Lending) Directions, 2025 [PLACEHOLDER]

- Clause count: **14**
- Verification status: **unverified** — Placeholder text — see data/raw/instruments/README.md. Real text is regulator-hosted per PRD §10 once supplied.
- Detected paragraph range: `1` .. `17`
- Parser warnings (4):
  - paragraph 6 does not increment by one (previous sort key 1)
  - paragraph 8 does not increment by one (previous sort key 6)
  - paragraph 13 does not increment by one (previous sort key 11)
  - paragraph 17 does not increment by one (previous sort key 13)

## KFS2024 — Key Facts Statement (KFS) for Loans & Advances [PLACEHOLDER]

- Clause count: **17**
- Verification status: **unverified** — Placeholder text — see data/raw/instruments/README.md.
- Detected paragraph range: `` .. ``
- Parser warnings: none

## RBC2025 — Reserve Bank of India (Non-Banking Financial Companies – Responsible Business Conduct) Directions, 2025

- Clause count: **211**
- Verification status: **unverified** — CORRECTED (2026-09-21): the PDF actually matching this instrument is the one named 329f97d5-362MD26CA... (sha256 baed420340e983d696cc1b6546bdd4513bd4e658977715c5f00a096714a3a559 of the ORIGINAL PDF) -- an earlier note here wrongly attributed a different PDF (837daa67..., which is actually the NBFC Miscellaneous Directions, circular 373, not this one) based on upload-order guessing rather than reading the PDF's own title page. The real circular number printed on page 1 of the correct PDF, 'RBI/DOR/2025-26/362 / DOR.MCS.REC.No.281/01-01-039/2025-26', matches exactly what was already recorded here as a placeholder guess -- strong independent confirmation. Real RBI-hosted source: https://rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12931 (not id=12942 as previously and wrongly noted) -- unreachable from this environment (rbi.org.in 403s at the proxy, SQ-01), so source_url stays local. data/raw/instruments/rbc2025.txt now holds the REAL extracted PDF text (66881 chars, 37 pages, pypdf extraction) in place of the fabricated placeholder -- paragraphs 35 (release timeline), 39 (compensation), 40 (lost documents) match the real text exactly, confirming R01/R02/R02b's citations. paragraph 45 does NOT match R17's premise (microfinance contact hours) -- real para 45 concerns gold/silver collateral valuation methodology disclosure; the real general contact-hour restriction is paragraph 100, which explicitly EXCLUDES microfinance loans and defers to a separate, not-yet-ingested instrument (NBFC Credit Facilities Directions, 2025) -- see ADR-055. citable stays true only for R01/R02/R02b's paragraphs; R17's citation is flagged, not fixed, pending a decision -- do not treat verification_status=unverified as blanket-safe for every paragraph this instrument's rules cite.
- Detected paragraph range: `1` .. `109`
- Parser warnings: none

## RBC-AMD2026 — RBC Amendment Directions, 2026 — recovery of loans and engagement of recovery agents [PLACEHOLDER]

- Clause count: **10**
- Verification status: **secondary_sourced** — Circular number and text not confirmed against an RBI-hosted page (PRD §10). Placeholder text besides — see data/raw/instruments/README.md. Rules gated on this instrument run in shadow mode until both are resolved.
- Detected paragraph range: `100E` .. `100Y`
- Parser warnings: none

## RBC-AMD2026-DRAFT — Revised draft of the RBC Amendment Directions, 2026 [PLACEHOLDER]

- Clause count: **4**
- Verification status: **unverified** — Draft — never citable regardless of verification status. Placeholder text — see data/raw/instruments/README.md.
- Detected paragraph range: `100W` .. `100Z`
- Parser warnings: none

## Cross-reference edges

- `DL2025/p8/i` --incorporates--> `KFS2024`

## Open questions (PRD §14, Q1–Q5)

1. Recovery amendment circular number/date confirmed against a regulator-hosted page: **UNRESOLVED** — blocked on SQ-01 (network policy) and real source text (ADR-001).
2. Draft vs final paragraph numbering preserved: **UNRESOLVED** — same blocker.
3. Leaf-level sub-paragraph identifiers for RBC2025 KFS/penal/property/recovery-agent paragraphs: pinned at paragraph granularity (M1); tightening deferred to M5 per LLD §7.
4. General non-microfinance contact-hour provision before 2027: **UNRESOLVED against real text** — the placeholder corpus asserts none exists (RBC2025/p45 is scoped to microfinance only, RBC-AMD2026/p100W is the general provision but not yet in force), matching the PRD §11 example as written.
5. Amendment to either principal instrument since consolidated text was last stamped: **UNRESOLVED** — same blocker as Q1/Q2.
