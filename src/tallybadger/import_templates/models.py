from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

ImportColumnDataType = Literal["string", "numeric", "date", "datetime"]


class ImportTemplateColumn(BaseModel):
    """One CSV column (by index in the stored array: 0 = first column)."""

    attribute_name: str | None = Field(default=None, max_length=200)
    data_type: ImportColumnDataType = "string"
    date_format: str | None = Field(default=None, max_length=120)

    @field_validator("attribute_name", mode="before")
    @classmethod
    def normalize_attribute_name(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return str(value)

    @model_validator(mode="after")
    def date_format_rules(self) -> Self:
        if self.data_type in ("date", "datetime"):
            df = (self.date_format or "").strip()
            if not df:
                raise ValueError("date_format is required when data_type is date or datetime")
            if "%" in df:
                raise ValueError(
                    "date_format must use Pendulum tokens (e.g. YYYY-MM-DD, M/D/YYYY), not POSIX % tokens",
                )
            if any(ord(c) < 32 for c in df):
                raise ValueError("date_format may not contain control characters")
            object.__setattr__(self, "date_format", df)
        else:
            object.__setattr__(self, "date_format", None)
        return self
