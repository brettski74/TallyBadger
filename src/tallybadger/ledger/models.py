from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["asset", "liability", "equity", "revenue", "expense"]
PartyRole = Literal["customer", "vendor", "both", "other"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    is_active: bool = True


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PartyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: PartyRole = "both"
    is_active: bool = True


class PartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: PartyRole | None = None
    is_active: bool | None = None


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: PartyRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class JournalLineIn(BaseModel):
    account_id: int = Field(gt=0)
    party_id: int | None = Field(default=None, gt=0)
    amount: Decimal


class JournalLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_name: str
    party_id: int | None
    party_name: str | None
    amount: Decimal


class JournalEntryWrite(BaseModel):
    entry_date: date
    summary: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    lines: list[JournalLineIn] = Field(min_length=2)


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    summary: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[JournalLineOut]


class JournalEntryListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    summary: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    debit_side_label: str
    credit_side_label: str
    party_labels: str
    amount: Decimal


class AccountLedgerLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_id: int
    entry_id: int
    entry_date: date
    description: str | None
    amount: Decimal
