# ClauseCheck — Build Kickoff Prompts

| | |
|---|---|
| **Document** | Build Kickoff Prompts — coding-agent handoff |
| **Product** | ClauseCheck |
| **Version** | 1.0 |
| **Date** | 19 September 2026 |
| **Audience** | The engineer driving the build |

Three prompts. The first starts the build. The second starts every later session. The third
is the template for handing over a single task.

**Before pasting anything**, put these five files in the repository root:

```
CLAUDE.md                                  ← agent operating rules (filename fixed by tooling)
ClauseCheck_PRD_v1.0.md                    ← product requirements
ClauseCheck_HLD_v1.0.md                    ← architecture
ClauseCheck_LLD_v1.0.md                    ← implementation specification
ClauseCheck_Build_Kickoff_Prompts_v1.0.md  ← this file
```

---

## Prompt 1 — kickoff (paste once, into an empty repository)

```
You are building ClauseCheck, a regulation-grounded lending compliance auditor for Indian
NBFCs. This repository contains five documents and no code yet.

Read these three in this order before writing anything:
  1. CLAUDE.md                  — how to work in this repo. Section 2 is binding.
  2. ClauseCheck_PRD_v1.0.md    — what the product is and who it is for.
  3. ClauseCheck_LLD_v1.0.md    — the implementation specification. This is your build authority.
Read ClauseCheck_HLD_v1.0.md when you need the reasoning behind a structural decision.

Context about me and about this project, which changes how you should work:

I am an AI engineer with about fourteen months of experience. This is a portfolio system
whose purpose is to demonstrate production judgment, and I will be questioned on every
design decision in interviews. Three consequences.

First, I need to understand the code, not just possess it. When you make a non-obvious
choice, record it in docs/DECISIONS.md as a short ADR: what you chose, what you rejected,
why. Explain the shape of what you are doing and the tradeoffs you hit. Do not explain
Python to me.

Second, citation correctness outranks feature count. A plausible-sounding clause reference
that does not resolve in the corpus is the worst possible defect in this system — worse
than a missing feature, worse than a failing test. The LLD records which regulatory facts
are confirmed against a regulator-hosted source and which are not. Treat that distinction
as load-bearing.

Third, I would rather ship six measured things than twenty asserted ones. Follow the
milestone order in LLD section 21. Do not run ahead of it.

I build by directing coding agents while keeping the architecture and the decisions my own.
So do not ask me to approve things the LLD already settles, and do not soften a
disagreement — if you think the spec is wrong, say so plainly.

Your first three actions, in order:

1. Read CLAUDE.md, the PRD, and the LLD completely.

2. Write TASKS.md. Take LLD section 21 and expand it into ordered, individually shippable
   tasks. Preserve the task ids (M1-T01 and so on). For each, add: the files it touches,
   its dependencies, and acceptance criteria stated as something runnable. An acceptance
   criterion that cannot be checked by running a command or a test is written wrong —
   rewrite it until it can. Do not start coding until TASKS.md exists.

3. Then tell me three things and stop for my reply:
   - anything in the LLD you believe is wrong, internally inconsistent, or unimplementable
     as written;
   - anything you need from me that the documents do not supply (API keys, accounts,
     decisions I have not made);
   - the specific first task you intend to start.

After I reply, begin M1.

A note on M1, because it is easy to get wrong. M1 is the regulation corpus, and it comes
first because every other component's correctness is defined relative to it. Its real
deliverable is not working code — it is docs/CORPUS.md, reporting what the parsers actually
found in the live regulator sources: clause counts, the full clause-path list, parser
warnings, the detected paragraph range against the expected range, the cross-reference
edges, and a promotion or correction of every instrument's verification status. Several
clause facts in these documents are explicitly marked unverified. Resolving them from the
live sources is the work. If a source is unreachable or a fact cannot be confirmed, record
it as an unresolved gap and leave the instrument marked secondary-sourced. Do not fill a gap
with something that sounds right.

Two constraints for every session after this one. Commit in small increments with passing
tests, one branch per task. And when you finish a task, report: what you built, what you
measured as numbers rather than adjectives, what you could not do and why, and what you
recommend next.
```

---

## Prompt 2 — resuming (paste at the start of every later session)

```
Continuing ClauseCheck. Read CLAUDE.md, then TASKS.md, then the sections of
ClauseCheck_LLD_v1.0.md relevant to the next open task. Check git log and git status to see
where the last session stopped.

Tell me: the current state — what is done, what is in flight, what is broken; the next task
you intend to start; and anything that has changed since the specification was written that
makes a planned task wrong.

Then start.

Do not re-plan work that is already done. Do not refactor working code unless the task
requires it. If you find a defect in earlier work, tell me before fixing it, so I know it
happened.
```

---

## Prompt 3 — task handover template

Replace the bracketed parts.

```
Next task: [M4-T02 — vector retrieval with applicability filtering in SQL].

Read ClauseCheck_LLD_v1.0.md sections [8.1 and 8.2] for the specification, and CLAUDE.md
section 2 for the invariants this touches — in particular [retrieval must never run without
an explicit as_of date, and the applicability filter must be applied in the query rather
than after it].

Acceptance criteria from TASKS.md:
[paste them]

Before you start, tell me in three or four sentences how you intend to implement it and
where you see the risk. If your approach differs from the specification, say so and say why.
The spec can be wrong; I would rather change it than have you deviate from it silently.

When you are done: run the relevant evaluation suite, put the numbers in your summary
alongside the previous run's numbers, and state the delta. For this milestone, a summary
without numbers is not a completed task.
```

---

## What to have ready, by milestone

Nothing blocks M1 and M2 beyond a local Docker installation, so start there and provision the
rest as the milestones need it.

| Milestone | Needed | Approximate cost |
|---|---|---|
| M1–M2 | Docker and Docker Compose locally | — |
| M3 | One frontier-model API key and one embedding-model key, both via LiteLLM | a few dollars of usage |
| M4–M7 | Nothing new | model usage during evaluation runs |
| M8 | Hosting accounts per LLD §20.2, and `docs/COSTS.md` filled in with prices verified on the day | ~$20–24 per month |
| M9 | A GPU rental account | ~$3–5 fine-tune, ~$10–15 benchmark runs |

Total out of pocket through the release gate is on the order of forty to sixty dollars, most
of it the three months of hosting that keep the demonstration clickable while interviewing.

---

## Two proposals to refuse

**An agent or planner inside the assessment path.** The LLD replaced an open-ended planner
with a deterministic conflict trigger deliberately. If a coding agent proposes autonomous
tool use anywhere in extraction, retrieval or verdict, the answer is no. The reason is not
taste: an open-ended planner cannot be asserted about in a test, and the evaluation suite is
the product's central claim.

**Judgement fields on extracted facts.** The moment `is_violation` or `severity` appears on
an extracted fact, the architecture is gone — extraction stops being a closed-schema task,
the fine-tune stops being justifiable, and the verdict stage stops being the only path to a
finding. Facts state what a document says. Nothing more.

---

## The one behaviour to check before believing the system works

Run the temporal pair. The same collections transcript, one contact at 20:10 on 3 September
2026 and one at 20:10 on 3 January 2027, on a non-microfinance personal loan.

The first must return `no_clause_found`, with the 08:00–19:00 provision attached as
context-only and annotated with its 1 January 2027 commencement, and the microfinance
contact-hour provision attached as context-only and annotated as out of scope for this
borrower class.

The second must return `violation`, citing the provision decisively.

If both return `violation`, the applicability filter is not working and nothing else in the
system can be trusted. If both return `no_clause_found`, the amendment's effective window is
wrong in the corpus. This pair is the fastest single check on whether the system understands
the rulebook or is matching keywords.
