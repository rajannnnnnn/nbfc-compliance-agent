"""The mandatory as_of / entity / citable filter. LLD §8.1.

The filter is a composable SQL fragment, never applied in Python after the fact, because
post-filtering an ANN search silently reduces recall.

Adds the borrower-class predicate absent from the LLD's own DDL (ADR-005): without it, the
microfinance contact-hour clause passes every other predicate on a non-microfinance loan and
sits in `candidates` free to be cited decisively — which is exactly the failure PRD §11's own
diagnostic calls unrecoverable ("the applicability filter is not working and nothing else in
the system can be trusted").
"""

from datetime import date

APPLICABILITY_SQL = """
  c.snapshot_id = :snapshot_id
  AND c.citable = true
  AND i.citable = true
  AND :entity_type = ANY (i.applies_to_entity_types)
  AND (c.applies_to_borrower_classes = '{}' OR :borrower_class = ANY (c.applies_to_borrower_classes))
  AND (c.effective_from IS NULL OR c.effective_from <= :as_of)
  AND (c.effective_to   IS NULL OR c.effective_to   >  :as_of)
  AND (i.effective_from IS NULL OR i.effective_from <= :as_of)
  AND (i.effective_to   IS NULL OR i.effective_to   >  :as_of)
  AND i.status <> 'draft'
"""

# ADR-012: the context_only re-query drops only the two date-predicate pairs. status<>'draft'
# and both citable checks stay enforced — a draft clause must never reach any citation role,
# in any circumstance, per PRD §10 and every eval case's forbidden_citations assertion.
CONTEXT_ONLY_SQL_NO_DATES = """
  c.snapshot_id = :snapshot_id
  AND c.citable = true
  AND i.citable = true
  AND :entity_type = ANY (i.applies_to_entity_types)
  AND i.status <> 'draft'
"""

# The complement of the borrower-class predicate alone — used to find clauses excluded
# *only* by borrower scope, so they can be surfaced as context with reason='borrower_scope'
# (ADR-005) rather than silently dropped.
CONTEXT_ONLY_BORROWER_SCOPE_SQL = """
  c.snapshot_id = :snapshot_id
  AND c.citable = true
  AND i.citable = true
  AND :entity_type = ANY (i.applies_to_entity_types)
  AND NOT (c.applies_to_borrower_classes = '{}' OR :borrower_class = ANY (c.applies_to_borrower_classes))
  AND (c.effective_from IS NULL OR c.effective_from <= :as_of)
  AND (c.effective_to   IS NULL OR c.effective_to   >  :as_of)
  AND (i.effective_from IS NULL OR i.effective_from <= :as_of)
  AND (i.effective_to   IS NULL OR i.effective_to   >  :as_of)
  AND i.status <> 'draft'
"""


class ApplicabilityError(Exception):
    pass


def require_as_of(as_of: date | None) -> date:
    if as_of is None:
        raise ApplicabilityError("retrieval requires an explicit as_of date")
    return as_of
