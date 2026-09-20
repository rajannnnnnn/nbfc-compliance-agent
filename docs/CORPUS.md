# Corpus Ingest Report

Snapshot: `01a0c002-facf-74b7-b9ef-7c79fe736def`
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

## RBC2025 — RBI (NBFC – Responsible Business Conduct) Directions, 2025 [PLACEHOLDER]

- Clause count: **11**
- Verification status: **unverified** — Placeholder text — see data/raw/instruments/README.md.
- Detected paragraph range: `29` .. `45`
- Parser warnings (2):
  - paragraph 35 does not increment by one (previous sort key 30)
  - paragraph 45 does not increment by one (previous sort key 40)

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
