"""Typed fact values. Money is integer paise and rates are integer basis points because float
arithmetic in a compliance rule is a defect waiting to be found."""

from datetime import date, datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class Span(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quoted: str
    verified: bool = False

    @model_validator(mode="after")
    def _ordered(self) -> "Span":
        if self.end <= self.start:
            raise ValueError("span end must exceed start")
        return self


class DateValue(BaseModel):
    kind: Literal["date"] = "date"
    v: date


class DateTimeValue(BaseModel):
    kind: Literal["datetime"] = "datetime"
    v: datetime


class TimeValue(BaseModel):
    kind: Literal["time"] = "time"
    v: time


class MoneyValue(BaseModel):
    kind: Literal["money"] = "money"
    paise: int
    currency: str = "INR"


class RateValue(BaseModel):
    kind: Literal["rate_bps"] = "rate_bps"
    bps: int


class IntValue(BaseModel):
    kind: Literal["integer"] = "integer"
    v: int


class DaysValue(BaseModel):
    kind: Literal["duration_days"] = "duration_days"
    days: int


class BoolValue(BaseModel):
    kind: Literal["boolean"] = "boolean"
    v: bool


class EnumValue(BaseModel):
    kind: Literal["enum"] = "enum"
    v: str


class StringValue(BaseModel):
    kind: Literal["string"] = "string"
    v: str


FactValue = Annotated[
    DateValue
    | DateTimeValue
    | TimeValue
    | MoneyValue
    | RateValue
    | IntValue
    | DaysValue
    | BoolValue
    | EnumValue
    | StringValue,
    Field(discriminator="kind"),
]


class ExtractedFactIn(BaseModel):
    field_key: str
    value: FactValue | None = None
    value_raw: str | None = None
    is_absent: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    span: Span | None = None

    @model_validator(mode="after")
    def _absent_xor_value(self) -> "ExtractedFactIn":
        if self.is_absent and (self.value is not None or self.span is not None):
            raise ValueError("absent fact carries no value and no span")
        if not self.is_absent and self.value is None:
            raise ValueError("present fact requires a value")
        return self


class ExtractedFactOut(ExtractedFactIn):
    id: UUID
    document_id: UUID
    loan_account_id: UUID


def value_to_jsonable(value: FactValue) -> dict[str, Any]:
    """Renders a FactValue as the {"kind": ..., ...} shape stored in extracted_fact.value_normalized."""
    return value.model_dump(mode="json")
