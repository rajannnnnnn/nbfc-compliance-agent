"""Every enum in one place. DB enums (migration 0001) are generated from these string lists."""

from enum import StrEnum


class EntityType(StrEnum):
    NBFC = "nbfc"
    BANK = "bank"
    HFC = "hfc"
    UCB = "ucb"


class BorrowerClass(StrEnum):
    """Not a DB enum — used as the retrieval-time predicate value. See ADR-005."""

    GENERAL = "general"
    MICROFINANCE = "microfinance"


class LifecycleStage(StrEnum):
    ORIGINATION = "origination"
    SANCTION = "sanction"
    DISBURSEMENT = "disbursement"
    SERVICING = "servicing"
    COLLECTIONS = "collections"
    CLOSURE = "closure"


class DocType(StrEnum):
    KFS = "kfs"
    LOAN_AGREEMENT = "loan_agreement"
    SANCTION_LETTER = "sanction_letter"
    MITC = "mitc"
    CALL_TRANSCRIPT = "call_transcript"
    CLOSURE_STATEMENT = "closure_statement"
    NOC = "noc"
    DOCS_RELEASE_ACK = "docs_release_ack"
    CHARGE_SATISFACTION = "charge_satisfaction"
    LOAN_APPLICATION = "loan_application"
    KYC_SET = "kyc_set"
    INCOME_PROOF = "income_proof"
    BUREAU_REPORT = "bureau_report"
    VALUATION_REPORT = "valuation_report"
    FIELD_INVESTIGATION = "field_investigation"
    DISBURSEMENT_MEMO = "disbursement_memo"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    ACCOUNT_STATEMENT = "account_statement"
    RATE_RESET_NOTICE = "rate_reset_notice"
    PENAL_CHARGE_NOTICE = "penal_charge_notice"
    REMINDER_NOTICE = "reminder_notice"
    FIELD_VISIT_REPORT = "field_visit_report"
    DEMAND_NOTICE = "demand_notice"
    SETTLEMENT_LETTER = "settlement_letter"
    POSSESSION_NOTICE = "possession_notice"
    UNKNOWN = "unknown"


class ValueType(StrEnum):
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    MONEY = "money"
    RATE_BPS = "rate_bps"
    INTEGER = "integer"
    DURATION_DAYS = "duration_days"
    BOOLEAN = "boolean"
    ENUM = "enum"
    STRING = "string"


class InstrumentStatus(StrEnum):
    IN_FORCE = "in_force"
    NOTIFIED_NOT_YET_EFFECTIVE = "notified_not_yet_effective"
    DRAFT = "draft"
    SUPERSEDED = "superseded"


class VerificationStatus(StrEnum):
    RBI_VERIFIED = "rbi_verified"
    SECONDARY_SOURCED = "secondary_sourced"
    UNVERIFIED = "unverified"


class ChunkKind(StrEnum):
    CLAUSE = "clause"
    TABLE_ROW = "table_row"
    ILLUSTRATION = "illustration"
    DEFINITION = "definition"


class Verdict(StrEnum):
    COMPLIANT = "compliant"
    VIOLATION = "violation"
    AMBIGUOUS = "ambiguous"
    NO_CLAUSE_FOUND = "no_clause_found"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFORMATIONAL = "informational"


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecidedBy(StrEnum):
    RULE = "rule"
    MODEL = "model"
    VALIDATOR_DOWNGRADE = "validator_downgrade"
    SHADOW = "shadow"


class CitationRole(StrEnum):
    DECISIVE = "decisive"
    SUPPORTING = "supporting"
    CONTEXT_ONLY = "context_only"


class RetrievalSource(StrEnum):
    PINNED = "pinned"
    VECTOR = "vector"
    LEXICAL = "lexical"
    REFERENCE_HOP = "reference_hop"


class ConflictType(StrEnum):
    VALUE_MISMATCH = "value_mismatch"
    DATE_ORDER = "date_order"
    TOLERANCE_BREACH = "tolerance_breach"
    MISSING_COUNTERPART = "missing_counterpart"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class ServingMode(StrEnum):
    HOSTED_BASELINE = "hosted_baseline"
    TUNED_GPU = "tuned_gpu"
    ON_PREM = "on_prem"


class ExclusionReason(StrEnum):
    """Why a context_only clause was excluded from citability. See ADR-005, ADR-012."""

    NOT_YET_IN_FORCE = "not_yet_in_force"
    SUPERSEDED = "superseded"
    BORROWER_SCOPE = "borrower_scope"
    DRAFT = "draft"


class CitationRejectReason(StrEnum):
    NOT_OFFERED = "not_offered"
    NOT_IN_FORCE = "not_in_force"
    NOT_CITABLE = "not_citable"
    EXCERPT_NOT_SUBSTRING = "excerpt_not_substring"
