from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["asset", "liability", "equity", "revenue", "expense"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    is_active: bool = True


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    is_active: bool
    created_at: datetime
    updated_at: datetime


class JournalLineIn(BaseModel):
    account_id: int = Field(gt=0)
    amount: Decimal


class JournalLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    amount: Decimal


class JournalEntryWrite(BaseModel):
    entry_date: date
    description: str | None = Field(default=None, max_length=500)
    lines: list[JournalLineIn] = Field(min_length=2)


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    description: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[JournalLineOut]
