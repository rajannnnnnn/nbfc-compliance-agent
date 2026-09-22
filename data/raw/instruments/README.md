# Bring your own RBI corpus here

This directory is gitignored except this file — nothing you place here is committed.

## What to place here

Five files, one per instrument in `app/corpus/corpus_sources.yaml`:

| Instrument code | Expected filename | Format |
|---|---|---|
| `DL2025` | `dl2025.txt` | Continuous paragraph numbering, lower-roman sub-clauses (`i.`, `ii.`), parenthesised-letter third level (`(a)`) |
| `KFS2024` | `kfs2024.txt` | A short main body (same convention as above) followed by a line containing exactly `=== ANNEX A ===`, then the KFS field-list annexe as a plain-text table: a header row, then rows starting `1.`, `2.`, `3.` … |
| `RBC2025` | `rbc2025.txt` | Continuous paragraph numbering, parenthesised-numeral sub-clauses (`(1)`, `(2)`), parenthesised-letter third level |
| `RBC-AMD2026` | `rbc_amd2026.txt` | Same convention as RBC2025 |
| `RBC-AMD2026-DRAFT` | `rbc_amd2026_draft.txt` | Same convention; ingested but never citable regardless of content |

Extract each as plain text (prefer the regulator's HTML view, not the PDF — HLD §4.4). Do not
hand-edit clause text once ingested; if the parser gets something wrong, fix the parser and
re-ingest (`CLAUDE.md` §2.5).

## What happens right now, before you place anything

Five **placeholder** files already exist here, each opening with a loud
`⚠ PLACEHOLDER TEXT — NOT OFFICIAL RBI TEXT` banner. They exist only so the pipeline,
retrieval, rule engine and verdict validator can be exercised end-to-end today. Their numeric
content (30-day release window, ₹5,000/day compensation, the 08:00–19:00 contact window, and
so on) is drawn only from figures the product's own `ClauseCheck_PRD_v1.0.md` and
`ClauseCheck_LLD_v1.0.md` already state as the regulatory facts under audit — nothing beyond
that is asserted as real RBI text.

Every placeholder instrument carries `verification_status: unverified` in
`app/corpus/corpus_sources.yaml`, which puts **every rule resting on it into shadow mode**
automatically (`shadow_if_unverified=True`, LLD §11.2): the system computes and measures every
check, but emits no citable finding until you replace the text. See `docs/DECISIONS.md`
ADR-001.

## Going live

1. Replace the file(s) above with the real extracted text.
2. In `app/corpus/corpus_sources.yaml`, set `verification_status` honestly — `rbi_verified`
   only if you hashed the text against a source you can name, `secondary_sourced` otherwise.
3. `make ingest` — parses, chunks, embeds, and activates a new snapshot; writes
   `docs/CORPUS.md` reporting exactly what was found.
4. `make corpus-verify` re-fetches the same local paths and reports drift the next time you
   edit them, the same way it would report drift against a live URL.

Rules resting on an instrument you promote to `rbi_verified` or `secondary_sourced` leave
shadow mode automatically on the next ingest — no code change.
