# ClauseCheck — Product Requirements Document

| | |
|---|---|
| **Document** | Product Requirements Document (PRD) |
| **Product** | ClauseCheck — RBI-grounded lending compliance auditor |
| **Version** | 1.0 |
| **Date** | 19 September 2026 |
| **Author** | N Rajan |
| **Status** | Approved for build |
| **Audience** | Executive / product / engineering leadership; technical interviewers |
| **Companion documents** | `ClauseCheck_HLD_v1.0.md` (architecture), `ClauseCheck_LLD_v1.0.md` (implementation) |

---

## 1. Executive summary

Indian non-banking financial companies are audited against a rulebook that changed three
times in eighteen months. In May 2025 the Reserve Bank of India repealed the 2022 digital
lending guidelines and replaced them with consolidated Directions. In November 2025 it
folded the NBFC Fair Practices Code and a dozen satellite circulars into a single
Responsible Business Conduct instrument. In August 2026 it notified an amendment governing
loan recovery and recovery agents, effective 1 January 2027. A compliance team at a
mid-sized NBFC is therefore checking today's loan files against one rulebook, last
quarter's files against another, and preparing for a third that has not yet commenced.

They do this manually, in spreadsheets, on a sample of accounts, and the work is slow
enough that sampling rates are low and findings arrive after the quarter has closed.

ClauseCheck automates the audit itself. A compliance analyst submits a loan file — the Key
Facts Statement, the loan agreement, the closure set, a collections-call transcript — and
receives, per obligation, a verdict of compliant, violation, ambiguous, or no applicable
clause, each one carrying the exact RBI clause identifier, the clause text, and the
effective window that made that clause applicable on the date of the event being judged.

The product's differentiator is not extraction accuracy. It is **citation discipline**:
the system cannot produce a finding it cannot cite, it cannot cite a provision that was
not in force when the event happened, and it declines to find a violation where the
rulebook was silent rather than manufacturing one. Those three properties are enforced in
code, not in prompt text, and they are what makes output usable in front of a regulator.

## 2. Problem statement

### 2.1 The work today

Compliance review at a retail NBFC is document reconciliation performed by hand. An
analyst opens a loan file, reads the Key Facts Statement, checks that the Annual
Percentage Rate disclosed there matches the one in the loan agreement, checks that the
cooling-off period is stated, checks that the grievance officer's phone number and email
are present, checks that disbursal went to the borrower's own account rather than through
a lending service provider's pool account, and then — for a closed loan — checks that
original property documents were released within thirty days of full repayment and that
₹5,000 per day of delay was paid where they were not. For collections, the analyst reads
call logs looking for contact outside permitted hours, contact with the borrower's
relatives or colleagues, abusive language, or device-locking applied without the
prescribed cure notices.

Every one of these checks is mechanical. Each takes minutes. A file has dozens. An NBFC
has hundreds of thousands of files.

### 2.2 Why the obvious solutions fail

**A rules engine over structured data** fails because the facts are not structured. They
are in PDFs, some of them scanned, in layouts that differ by product and by vintage.

**A general-purpose LLM asked "is this loan compliant?"** fails in three ways that matter.
It answers from whatever Indian lending law was in its training data, which is now at
least one repeal out of date. It produces confident findings citing provisions that do not
exist or that had not commenced. And when it is wrong you cannot tell whether it misread
the document, recalled the wrong rule, or reasoned badly — so you cannot fix it.

**Keyword search over the circulars** fails because the question is never "does the word
'thirty days' appear" but "which of four overlapping instruments governed this obligation
on 3 September 2026, and does this document satisfy it".

### 2.3 What makes this hard, honestly

The corpus is a moving target with overlapping temporal layers. The same obligation can be
governed by different text depending on the event date. A notified amendment may not yet
be in force. A draft may never be. A consolidated master direction on the regulator's own
site can be updated underneath you without notice. And the highest-value findings depend
on arithmetic over dates and money, where a system that is approximately right is worse
than useless.

## 3. Why now

The regulatory churn described in §1 is the market timing. Three things follow from it.

Lenders are currently re-papering their document sets against instruments issued in the
last eighteen months, so the cost of a disclosure defect is unusually visible. The
recovery amendment effective 1 January 2027 imposes obligations — recovery-agent
certification, call-recording retention, prior intimation before a visit, narrow
preconditions for restricting a financed device — that no existing manual process is
configured to check. And a lender preparing for that commencement date needs to audit
conduct under both the current and the incoming rulebook, which is precisely the
capability that distinguishes a date-aware system from a keyword matcher.

## 4. Users

### 4.1 Primary persona — Compliance Analyst

Reviews loan files against the applicable rulebook, prepares findings for the compliance
head, and answers inspection queries. Works in spreadsheets today. Measured on files
reviewed and on findings that survive challenge. Wants the mechanical checks done for her
so she can spend her time on the judgement calls, and she will not trust a finding she
cannot trace to a clause she can read.

**Success for her:** submit a file, get back a list of findings each with the clause text
attached, and be able to hand that list to her head of compliance without re-checking it.

### 4.2 Secondary persona — Head of Compliance / Risk

Accountable for what the NBFC tells the regulator. Needs coverage statistics, severity
triage, and an audit trail showing what was checked, against which version of which
instrument, and when. Cares more about defensibility than about throughput.

**Success for him:** a portfolio view of open findings by severity, and the ability to
prove, for any historical finding, exactly which clause text and which corpus version
produced it.

### 4.3 Anti-persona — the borrower

ClauseCheck is not borrower-facing and produces no borrower-visible output. This is a
deliberate scope boundary: a borrower-facing grievance tool is a different product with a
different liability profile.

## 5. Jobs to be done

| Job | Today | With ClauseCheck |
|---|---|---|
| Check a sanction file for disclosure completeness | Analyst reads KFS and agreement side by side | Submit both, receive field-level findings with clause citations |
| Reconcile the same figure across documents | Manual comparison, often skipped | Deterministic conflict detection across the document set |
| Check a closure file against the release timeline | Date arithmetic by hand | Exact arithmetic with the compensation obligation computed |
| Audit a collections call for conduct breaches | Listen or read, judge from memory of the rules | Transcript assessed against the instrument in force on the call date |
| Prepare for the January 2027 recovery rules | Not possible systematically | Assess the same conduct under both current and incoming rulebooks |
| Answer an inspection query on a past finding | Reconstruct from notes | Retrieve the assessment with its clause citations and corpus version |

## 6. Product scope — version 1

### 6.1 Capabilities

**Fact extraction.** Typed facts from six document types given deep treatment (Key Facts
Statement, loan agreement, sanction letter, Most Important Terms & Conditions,
collections-call transcript, closure set) and shallow treatment of the rest. Roughly sixty
fields, each typed, normalised and evidenced by a redacted quotation from the source.
Absence of a required field is recorded explicitly, because a missing disclosure is itself
a finding.

**Temporal clause retrieval.** Every retrieval is scoped to the date of the event being
judged. Provisions not yet commenced are excluded from the citable set and surfaced
separately as context. Superseded instruments are retained so the system can explain why
it did not cite them.

**Cited verdicts.** Four outcomes, three of which require at least one valid citation and
the fourth of which requires none by definition. Verdicts are produced by deterministic
rules wherever the obligation is arithmetic, and by a frontier model over retrieved clause
text where it is not.

**Cross-document conflict detection.** Twelve conflict groups covering the figures and
dates that must agree across a loan's own documents, evaluated deterministically on
normalised values.

**Audit trail.** Per finding: the clause paths cited, the instrument versions, the corpus
snapshot hash, the model and prompt versions, per-stage latency and cost. Append-only.

**Public corpus manifest.** An unauthenticated endpoint listing every instrument in the
corpus with its source URL, retrieval timestamp, content hash, and verification status.

### 6.2 Out of scope for v1

Credit decisioning and underwriting quality, which is a different product. Prudential
norms, capital adequacy, non-performing-asset classification, and the Default Loss
Guarantee chapter of the digital lending instrument, all of which are portfolio-level and
do not follow from single-document facts. Entity types other than NBFCs, which are
governed by parallel but distinct instruments. Languages other than English. Speech-to-text
— transcripts are ingested as text.

### 6.3 Explicit non-goals

The product does not give legal advice and says so on every output. It does not resolve
genuine regulatory ambiguity; it surfaces it with the competing clauses attached, which is
both the honest answer and, for a compliance team, the useful one. It does not attempt
real-time operation: it is retrospective by design, because the latency and
non-determinism of language models have no place in a disbursal or payment path.

## 7. Differentiation

The category — AI compliance tooling for Indian lending — has entrants. The defensible
position here is not model quality, which commoditises, but four properties that are
architectural and therefore hard to retrofit.

**Citation validation in code.** A verdict whose citations do not resolve to real,
in-force clauses is rejected by a validator before persistence. Competitors relying on
prompt instructions to prevent fabricated citations cannot make this guarantee.

**Temporal applicability as a first-class concept.** Clauses carry effective windows;
retrieval requires an as-of date; supersessions are stored as data. Most retrieval systems
in this space treat the corpus as timeless, which produces confidently wrong answers in
both directions.

**Principled abstention.** The system reports "no provision in force governed this" as a
distinct outcome and is evaluated on getting it right. This is the property a compliance
head cares about most and the one least likely to be present in a demo built to impress.

**No customer document retention.** The product stores hashes, pointers and redacted
evidence spans, never document bytes. In BFSI procurement this converts a security
objection into a selling point, and it is what makes an in-VPC deployment straightforward.

## 8. Success criteria

### 8.1 Product metrics (measured, published)

| Metric | Target v1 | Where measured |
|---|---|---|
| Extraction exact-match on normalised values | ≥90% across compliance-bearing fields | `extraction_core` suite |
| Span-grounding rate (evidence verifiably present in source) | ≥99% | `extraction_core` suite |
| Retrieval recall@4 of the decisive clause | ≥95% | `retrieval` suite |
| Applicability precision (retrieved clauses actually in force) | 100% | `retrieval` suite |
| Verdict accuracy on deterministic numeric rules | ≥99% | `numeric_rules` suite |
| Hallucinated citation rate | **exactly 0** | `verdict` suite — release blocker |
| Abstention correctness | ≥90% | `abstention` suite |
| End-to-end latency per document, p95 | <10 s | load test |
| Cost per document assessed | tracked and published | assessment rows |

### 8.2 Release gate

Version 1 ships when six things are true, and not before.

1. A live URL an evaluator can open at any hour and get a cited verdict from in under ten
   seconds, with no cold start and no signup.
2. Published baseline numbers for extraction, retrieval and verdicts, measured per stage.
3. A measured fine-tune delta against that baseline, with cost per document on both paths.
4. The full per-stage evaluation table including abstention and adversarial suites, with a
   hallucinated-citation rate of zero.
5. One load test with a named bottleneck, a fix, and before-and-after numbers.
6. A written technical account in which every figure traces to a file in `reports/`.

### 8.3 Deliberately deferred

Multiple deployment environments, a self-hosted metrics and dashboard stack, an incident
runbook, chaos injection, model drift detection, a production identity provider, billing,
and a customer-facing admin console. Each is a thing to have a considered answer about
rather than a thing to half-build. Scope discipline is itself a requirement of this
document.

## 9. Constraints and compliance posture

**Data minimisation.** Original bytes, full text, page images and OCR intermediates are
never persisted. What persists is a content hash, the tenant's own source pointer, typed
normalised values, and PII-redacted evidence spans capped at fifteen per cent of source
characters, enforced at write time.

**Localisation.** Infrastructure sits in an Indian region. Where a hosted model processes
text outside India, this is disclosed in the product and satisfied via a zero-retention
provider agreement, consistent with the requirement that data processed abroad be deleted
from offshore servers and brought back within twenty-four hours. The in-VPC deployment
path exists for customers who cannot accept off-shore processing at all.

**Tenancy.** Row-level security in the database, with the application connecting as a
non-superuser role so isolation is enforced rather than advisory.

**Data provenance.** No real borrower data is used in development, training or
demonstration. All fixtures and training examples are synthetic and labelled as such, in
the product and in the write-up. The accuracy figures are therefore synthetic-set figures
and are reported as such, with the pilot design that would measure real accuracy stated
rather than implied.

**Regulatory verification.** Every instrument carries a verification status recording
whether its text was confirmed against a regulator-hosted source. Rules resting on
unverified text run in shadow mode — they compute and record but do not emit a citable
verdict. The corpus manifest is public so that any claim the product makes about its own
grounding can be checked by the person hearing it.

## 10. Regulatory scope — instruments in the v1 corpus

| Code | Instrument | Reference | Issued | In force from | Verification |
|---|---|---|---|---|---|
| `DL2025` | RBI (Digital Lending) Directions, 2025 | RBI/2025-26/36 · DOR.STR.REC.19/21.07.001/2025-26 | 8 May 2025 | 8 May 2025; para 6 from 1 Nov 2025; para 17 from 15 Jun 2025 | Regulator-hosted |
| `KFS2024` | Key Facts Statement for Loans & Advances | RBI/2024-25/18 · DOR.STR.REC.13/13.03.00/2024-25 | 15 Apr 2024 | 1 Oct 2024 for new loans | Regulator-hosted |
| `RBC2025` | RBI (NBFC – Responsible Business Conduct) Directions, 2025 | RBI/DOR/2025-26/362 · DOR.MCS.REC.No.281/01-01-039/2025-26 | 28 Nov 2025 | from issuance | Regulator-hosted |
| `RBC-AMD2026` | RBC Amendment Directions, 2026 — recovery of loans and engagement of recovery agents | reported RBI/2026-2027/230 · DOR.MCS.REC.No.199/01-01-039/2026-27 | reported 6 Aug 2026 | **1 Jan 2027** | **Secondary-sourced — unconfirmed against a regulator-hosted page** |
| `RBC-AMD2026-DRAFT` | Revised draft of the above | DOR.MCS.REC.No./01-01-039/2026-27 | 20 May 2026 | never — draft | Regulator-hosted |

`DL2025` superseded three earlier circulars, including the September 2022 digital lending
guidelines, which are retained in the corpus as supersession records so the system can
explain their absence from citations. `RBC2025` absorbed the former NBFC Fair Practices
Code. `KFS2024` is in the corpus because `DL2025` does not restate the Key Facts Statement
field list — it cross-references that circular, whose annexe carries the mandated line
items. A corpus without it can establish that a KFS was issued but not whether it was
complete.

The draft is ingested deliberately, marked non-citable, so that clause text is available
for forward-looking review and so the evaluation suite can assert that draft text is never
cited in a finding. A corpus that silently omits drafts cannot prove it is not using them.

## 11. The behaviour that defines the product

A collections call is placed at 20:10 on 3 September 2026 to a borrower on a
non-microfinance personal loan.

The incoming recovery amendment permits contact only between 08:00 and 19:00. A system
that retrieves that provision and compares the timestamp returns a violation. That answer
is wrong: the amendment does not take effect until 1 January 2027. The instrument actually
in force on that date carries a contact-hour restriction only within its microfinance
conduct block, and this is not a microfinance loan.

The correct output is **no applicable clause**, with the incoming provision attached as
context and annotated with its commencement date, the microfinance provision attached as
context and annotated with its scope, and a plain statement that the conduct may still be
actionable under general fair-practice obligations but that no numeric window applies.

The same call on 3 January 2027 returns a violation, citing the amendment.

This pair is the first thing the product demonstrates, it is a permanent evaluation case,
and it is the single clearest answer to the question of whether the system understands the
rulebook or is matching keywords.

## 12. Release plan

| Milestone | Outcome | Gate |
|---|---|---|
| M1 | Regulation corpus ingested, parsed, hashed, verification statuses resolved against live sources | `make corpus-verify` passes; corpus manifest endpoint live |
| M2 | Schema, migrations, tenancy, API skeleton, queue wiring | `docker compose up` green; migrations reversible |
| M3 | Fact extraction on a frontier baseline; synthetic document set | First published baseline number |
| M4 | Temporal retrieval with pinning, vector and lexical recall | Retrieval measured independently of verdicts |
| M5 | The deterministic rule pack | Numeric and temporal suites near-perfect |
| M6 | Verdict stage and the citation validator | Hallucinated-citation rate zero |
| M7 | Conflict detection and portfolio compliance state | Conflict and end-to-end suites passing |
| M8 | Deployment, demonstration surface, load test with a fix | Live URL; bottleneck named and improved |
| M9 | Fine-tuned extraction adapter and the measured comparison | Accuracy, cost and latency delta published |

## 13. Principal risks

**The corpus could be wrong.** Highest-consequence risk in the product, since citation
accuracy is the entire value proposition. Mitigated by hash-pinning, a public manifest,
per-instrument verification status, shadow mode for unverified rules, and a weekly drift
check in continuous integration. The answer to "how do you know your clause text is right"
is a hash and a timestamp, not an assurance.

**The regulator will amend something mid-build.** It has done so twice during scoping
already. Mitigated structurally: instruments are versioned, clauses have effective
windows, supersessions are data, and every finding pins the corpus snapshot that produced
it, so historical findings remain reproducible.

**The fine-tuned extraction model may not beat the baseline on accuracy.** Acceptable and
reported as measured. Its justification is cost per document and in-VPC deployability,
both measurable independently of accuracy. Equal accuracy at a fraction of the
per-document cost, running inside the customer's own network, is the stronger claim
anyway.

**Serving economics for custom adapters have deteriorated.** Per-token serving of customer
fine-tuned adapters has largely left the market, which means the fine-tune cannot serve
the always-on demonstration at the target hosting budget. Handled by defining three
serving modes and recording which produced every result, rather than by concealing the
constraint.

**Synthetic training and evaluation data bounds what the accuracy figures mean.** Real
documents are messier. Stated in the product and the write-up, together with the pilot
design — a lender, an agreement, their documents, the adapter inside their network — that
would measure it properly.

**Scope drift.** The failure mode for this build is continued design instead of shipping.
Mitigated by sequential milestones each ending in a measurement, and by the rule that
anything not on the path to one of the six release-gate items waits until all six are
done.

## 14. Open questions carried into M1

1. Confirm the 6 August 2026 recovery amendment's circular number and effective date
   against a regulator-hosted page and retrieve its text. Until then it remains
   secondary-sourced and every rule depending on it runs in shadow mode.
2. Confirm whether the final amendment preserves the draft's paragraph numbering or
   renumbers it; the clause-pinning table depends on the answer.
3. Extract leaf-level sub-paragraph identifiers within the Responsible Business Conduct
   paragraphs covering the Key Facts Statement, penal charges, property-document release,
   and recovery-agent responsibilities, replacing paragraph-level rule bases.
4. Determine from the parsed text whether any general, non-microfinance contact-hour
   provision exists for NBFCs before January 2027. The §11 example assumes none; if one
   exists, that example and its evaluation cases change.
5. Check whether either principal instrument has been amended since its consolidated text
   was last stamped.
6. Confirm current pricing and, critically, idle-suspend behaviour for every hosting
   component before committing to the stack.
7. Re-verify base-model licences at the moment of the fine-tune rather than in advance.
