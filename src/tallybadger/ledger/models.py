from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from tallybadger.core.byte_size import parse_byte_size

AccountType = Literal["asset", "liability", "equity", "revenue", "expense", "suspense"]
PartyRole = Literal["customer", "vendor", "both", "other"]
AccrualDirection = Literal["revenue", "expense"]
AccrualFrequency = Literal["weekly", "monthly_day", "yearly"]
ObligationType = Literal["receivable", "payable", "unearned"]
ObligationStatus = Literal["open", "partially_settled", "settled", "reconciled"]
SettlementType = Literal["receipt", "payment"]


def _optional_byte_size(value: Any) -> int | None:
    if value is None:
        return None
    return parse_byte_size(value)


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
    subtype: str | None = Field(default=None, max_length=120)
    match_patterns: list[str] = Field(default_factory=list)
    default_revenue_account_id: int | None = Field(default=None, gt=0)
    default_expense_account_id: int | None = Field(default=None, gt=0)


class PartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: PartyRole | None = None
    is_active: bool | None = None
    subtype: str | None = Field(default=None, max_length=120)
    match_patterns: list[str] | None = None
    default_revenue_account_id: int | None = Field(default=None, gt=0)
    default_expense_account_id: int | None = Field(default=None, gt=0)


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: PartyRole
    is_active: bool
    subtype: str | None = None
    match_patterns: list[str] = Field(default_factory=list)
    default_revenue_account_id: int | None = None
    default_expense_account_id: int | None = None
    default_revenue_account_name: str | None = None
    default_expense_account_name: str | None = None
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
    requires_review: bool = False


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    summary: str
    description: str | None
    requires_review: bool = False
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


class AccrualPlanWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    direction: AccrualDirection
    party_id: int = Field(gt=0)
    target_account_id: int = Field(gt=0)
    bridge_account_id: int = Field(gt=0)
    frequency: AccrualFrequency
    start_date: date
    end_date: date
    amount: Decimal
    summary_template: str = Field(min_length=1, max_length=200)
    description_template: str | None = Field(default=None, max_length=500)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    month_of_year: int | None = Field(default=None, ge=1, le=12)
    business_day_adjust: bool = False

    @model_validator(mode="after")
    def validate_frequency_shape(self) -> "AccrualPlanWrite":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.amount <= Decimal("0"):
            raise ValueError("amount must be positive")

        if self.frequency == "weekly":
            if self.day_of_week is None:
                raise ValueError("weekly frequency requires day_of_week")
            if self.business_day_adjust:
                raise ValueError("business_day_adjust is only supported for monthly/yearly frequencies")
        elif self.frequency == "monthly_day":
            if self.day_of_month is None:
                raise ValueError("monthly_day frequency requires day_of_month")
        elif self.frequency == "yearly":
            if self.month_of_year is None or self.day_of_month is None:
                raise ValueError("yearly frequency requires month_of_year and day_of_month")

        return self


class AccrualPlanCreate(AccrualPlanWrite):
    pass


class AccrualPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    end_date: date | None = None
    amount: Decimal | None = None
    summary_template: str | None = Field(default=None, min_length=1, max_length=200)
    description_template: str | None = Field(default=None, max_length=500)
    force_override: bool = False


class AccrualPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    direction: AccrualDirection
    party_id: int
    target_account_id: int
    bridge_account_id: int
    frequency: AccrualFrequency
    start_date: date
    end_date: date
    amount: Decimal
    summary_template: str
    description_template: str | None
    day_of_week: int | None
    day_of_month: int | None
    month_of_year: int | None
    business_day_adjust: bool
    created_at: datetime
    updated_at: datetime


class AccrualPreviewItem(BaseModel):
    entry_date: date
    summary: str
    description: str | None
    lines: list[JournalLineIn]


class LedgerSettingsUpdate(BaseModel):
    accounts_receivable_account_id: int | None = Field(default=None, gt=0)
    accounts_payable_account_id: int | None = Field(default=None, gt=0)
    unearned_revenue_account_id: int | None = Field(default=None, gt=0)
    unallocated_debits_account_id: int | None = Field(default=None, gt=0)
    unallocated_credits_account_id: int | None = Field(default=None, gt=0)
    max_attachment_upload_bytes: Annotated[int | None, BeforeValidator(_optional_byte_size)] = Field(
        default=None,
        gt=0,
    )


class LedgerSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accounts_receivable_account_id: int | None
    accounts_payable_account_id: int | None
    unearned_revenue_account_id: int | None
    unallocated_debits_account_id: int | None
    unallocated_credits_account_id: int | None
    max_attachment_upload_bytes: int
    updated_at: datetime


class JournalEntryAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    summary: str
    external_reference: str | None
    mime_type: str
    original_filename: str | None
    created_at: datetime
    updated_at: datetime


class AccrualObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    party_id: int
    accrual_plan_id: int | None
    source_entry_id: int | None
    source_entry_date: date | None
    source_entry_summary: str | None
    source_line_id: int | None
    obligation_type: ObligationType
    status: ObligationStatus
    original_amount: Decimal
    open_amount: Decimal
    created_at: datetime
    updated_at: datetime


class SettlementAllocationIn(BaseModel):
    obligation_id: int = Field(gt=0)
    amount: Decimal = Field(gt=Decimal("0"))


class SettlementWrite(BaseModel):
    party_id: int = Field(gt=0)
    settlement_type: SettlementType
    event_date: date
    amount: Decimal = Field(gt=Decimal("0"))
    cash_account_id: int = Field(gt=0)
    allocations: list[SettlementAllocationIn] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=300)


class SettlementOut(BaseModel):
    event_id: int
    entry_id: int
    allocated_amount: Decimal
    unapplied_amount: Decimal


class ObligationStatusUpdate(BaseModel):
    status: ObligationStatus
    force_override: bool = False


class IncomeExpensePeriodEcho(BaseModel):
    start_date: date
    end_date: date


class IncomeExpenseAccountRowOut(BaseModel):
    account_id: int
    account_name: str
    account_type: Literal["revenue", "expense"]
    is_active: bool
    amount: Decimal


class IncomeExpenseReportOut(BaseModel):
    """Stable JSON contract for the Income & Expense report (schema version 1)."""

    report_schema_version: Literal[1] = 1
    period: IncomeExpensePeriodEcho
    currency_label: str
    preset: Literal["current_year_to_date", "prior_full_year", "prior_year_to_date"] | None = None
    exclude_zero_balance_accounts: bool
    revenue_accounts: list[IncomeExpenseAccountRowOut]
    expense_accounts: list[IncomeExpenseAccountRowOut]
    total_revenue: Decimal
    total_expense: Decimal
    net_income: Decimal
