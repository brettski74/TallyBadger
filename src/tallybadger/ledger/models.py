from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from tallybadger.core.byte_size import parse_byte_size
from tallybadger.ledger.date_range_math import (
    DateRangeMathError,
    parse_optional_entry_date_expression,
    resolve_entry_date_range,
)

AccountType = Literal["asset", "liability", "equity", "revenue", "expense", "suspense"]
PartyRole = Literal["customer", "vendor", "both", "other"]
AccrualDirection = Literal["revenue", "expense"]
AccrualFrequency = Literal["weekly", "monthly_day", "yearly"]
ObligationType = Literal["receivable", "payable", "unearned"]
ObligationStatus = Literal["open", "partially_settled", "settled", "reconciled"]
SettlementType = Literal["receipt", "payment"]
ChequeStatus = Literal["open", "cleared", "void"]


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
    type: AccountType | None = None


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
    obligation_id: int | None = Field(default=None, gt=0)
    """When set, ``abs(amount)`` is applied to this obligation (CSV ``obligation-id`` or manual create)."""


class JournalLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_name: str
    party_id: int | None
    party_name: str | None
    amount: Decimal


class JournalEntryReviewMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message: str
    created_at: datetime


class JournalEntryWrite(BaseModel):
    entry_date: date
    summary: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    lines: list[JournalLineIn] = Field(min_length=2)
    requires_review: bool = False
    """When true, at least one non-empty ``review_messages`` item is required (or existing messages on update)."""

    review_messages: list[str] = Field(default_factory=list)
    """New review reasons to append when creating or updating an entry (non-empty strings only)."""

    cheque_id: int | None = Field(default=None, gt=0)
    """Optional link to a row in ``cheques`` (clearing / register linkage)."""


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    summary: str
    description: str | None
    requires_review: bool = False
    cheque_id: int | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[JournalLineOut]
    review_messages: list[JournalEntryReviewMessageOut] = Field(default_factory=list)


class JournalEntryListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    summary: str
    description: str | None
    requires_review: bool = False
    cheque_id: int | None = None
    created_at: datetime
    updated_at: datetime
    debit_side_label: str
    credit_side_label: str
    party_labels: str
    amount: Decimal


ChequeAssociation = Literal["any", "with_cheque", "without_cheque"]

JOURNAL_ENTRY_PRESET_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "entry_date",
        "summary",
        "requires_review",
        "party_labels",
        "debit_label",
        "credit_label",
        "amount",
    },
)


class JournalEntryFilterPresetSortKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    direction: Literal["asc", "desc"]


class JournalEntryFilterPresetDefinition(BaseModel):
    """Serialised form of the journal entry list filter dimensions (#107).

    All fields are optional; ``None`` / empty list means "no restriction" on that
    dimension, identical to the API default.
    """

    model_config = ConfigDict(extra="forbid")

    from_date: str | None = None
    to_date: str | None = None
    needs_review: bool | None = None
    account_ids: list[int] = Field(default_factory=list)
    party_ids: list[int] = Field(default_factory=list)
    accrual_plan_ids: list[int] = Field(default_factory=list)
    amount_low: int | None = Field(default=None, ge=0)
    amount_high: int | None = Field(default=None, ge=0)
    cheque_association: ChequeAssociation = "any"
    import_basename: str | None = Field(default=None, max_length=512)
    sort: list[JournalEntryFilterPresetSortKey] = Field(default_factory=list)

    @field_validator("import_basename", mode="before")
    @classmethod
    def _normalize_import_basename(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("import_basename must be a string or null")
        stripped = value.strip()
        return stripped if stripped else None

    @field_validator("from_date", "to_date", mode="before")
    @classmethod
    def _coerce_date_expression(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        raise ValueError("from_date and to_date must be strings, dates, or null")

    @model_validator(mode="after")
    def _validate(self) -> "JournalEntryFilterPresetDefinition":
        if (
            self.amount_low is not None
            and self.amount_high is not None
            and self.amount_low > self.amount_high
        ):
            raise ValueError("amount_low must be less than or equal to amount_high")
        if self.from_date is not None or self.to_date is not None:
            try:
                resolved_from = parse_optional_entry_date_expression(self.from_date)
                resolved_to = parse_optional_entry_date_expression(self.to_date)
            except DateRangeMathError as exc:
                raise ValueError(str(exc)) from exc
            if self.from_date is not None and resolved_from is None:
                raise ValueError("from_date must not be empty")
            if self.to_date is not None and resolved_to is None:
                raise ValueError("to_date must not be empty")
            if (
                self.from_date is not None
                and self.to_date is not None
                and resolved_from is not None
                and resolved_to is not None
            ):
                try:
                    resolve_entry_date_range(self.from_date, self.to_date)
                except DateRangeMathError as exc:
                    raise ValueError(str(exc)) from exc
        for field_name in ("account_ids", "party_ids", "accrual_plan_ids"):
            for v in getattr(self, field_name):
                if v <= 0:
                    raise ValueError(f"{field_name} entries must be positive integers")
        for key in self.sort:
            if key.field not in JOURNAL_ENTRY_PRESET_SORT_FIELDS:
                raise ValueError(f"unknown sort field: {key.field}")
        return self


class JournalEntryFilterPresetWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: JournalEntryFilterPresetDefinition


class JournalEntryFilterPresetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    definition: JournalEntryFilterPresetDefinition | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "JournalEntryFilterPresetPatch":
        if self.name is None and self.definition is None:
            raise ValueError("at least one of name or definition must be provided")
        return self


class JournalEntryFilterPresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    definition: JournalEntryFilterPresetDefinition
    created_at: datetime
    updated_at: datetime


ChequeRegisterListStatus = Literal["open", "cleared", "void", "all"]

CHEQUE_REGISTER_PRESET_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "cheque_number",
        "summary",
        "issue_date",
        "cleared_date",
        "amount",
        "credit_account_id",
        "debit_account_id",
        "party_id",
    },
)


class ChequeRegisterFilterPresetSortKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    direction: Literal["asc", "desc"]


class ChequeRegisterFilterPresetDefinition(BaseModel):
    """Serialised cheque register filters and sort keys (#196).

    Optional fields mean no restriction on that dimension when applied.
    """

    model_config = ConfigDict(extra="forbid")

    status: ChequeRegisterListStatus | None = None
    party_ids: list[int | Literal["null"]] = Field(default_factory=list)
    credit_account_ids: list[int] = Field(default_factory=list)
    debit_account_ids: list[int] = Field(default_factory=list)
    issue_from_date: date | None = None
    issue_to_date: date | None = None
    cleared_from_date: date | None = None
    cleared_to_date: date | None = None
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=512)
    sort: list[ChequeRegisterFilterPresetSortKey] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def _normalize_summary(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("summary must be a string or null")
        stripped = value.strip()
        return stripped if stripped else None

    @model_validator(mode="after")
    def _validate(self) -> "ChequeRegisterFilterPresetDefinition":
        if (
            self.issue_from_date is not None
            and self.issue_to_date is not None
            and self.issue_from_date > self.issue_to_date
        ):
            raise ValueError("issue_from_date must be on or before issue_to_date")
        if (
            self.cleared_from_date is not None
            and self.cleared_to_date is not None
            and self.cleared_from_date > self.cleared_to_date
        ):
            raise ValueError("cleared_from_date must be on or before cleared_to_date")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount must be less than or equal to max_amount")
        for field_name in ("credit_account_ids", "debit_account_ids"):
            for v in getattr(self, field_name):
                if v <= 0:
                    raise ValueError(f"{field_name} entries must be positive integers")
        for v in self.party_ids:
            if isinstance(v, int) and v <= 0:
                raise ValueError("party_ids entries must be positive integers or null")
        for key in self.sort:
            if key.field not in CHEQUE_REGISTER_PRESET_SORT_FIELDS:
                raise ValueError(f"unknown sort field: {key.field}")
        return self


class ChequeRegisterFilterPresetWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: ChequeRegisterFilterPresetDefinition


class ChequeRegisterFilterPresetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    definition: ChequeRegisterFilterPresetDefinition | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ChequeRegisterFilterPresetPatch":
        if self.name is None and self.definition is None:
            raise ValueError("at least one of name or definition must be provided")
        return self


class ChequeRegisterFilterPresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    definition: ChequeRegisterFilterPresetDefinition
    created_at: datetime
    updated_at: datetime


class ImportBatchListItem(BaseModel):
    """One CSV import batch row for operator discovery (#136)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    basename: str
    loaded_at: datetime
    is_active: bool
    is_latest_loaded_import: bool = Field(
        default=False,
        description="True when this row is the most recent active import by loaded_at (#49 / #137).",
    )


class ChequeCreate(BaseModel):
    credit_account_id: int = Field(gt=0)
    debit_account_id: int = Field(gt=0)
    summary: str = Field(min_length=1, max_length=200)
    cheque_number: int = Field(gt=0)
    issue_date: date
    cleared_date: date | None = None
    amount: Decimal = Field(gt=0)
    party_id: int | None = Field(default=None, gt=0)
    status: ChequeStatus = "open"

    @model_validator(mode="after")
    def cleared_shape_matches_status(self) -> "ChequeCreate":
        if self.status == "cleared":
            if self.cleared_date is None:
                raise ValueError("cleared_date is required when status is cleared")
        elif self.cleared_date is not None:
            raise ValueError("cleared_date must be null unless status is cleared")
        return self


class ChequeUpdate(BaseModel):
    credit_account_id: int | None = Field(default=None, gt=0)
    debit_account_id: int | None = Field(default=None, gt=0)
    summary: str | None = Field(default=None, min_length=1, max_length=200)
    cheque_number: int | None = Field(default=None, gt=0)
    issue_date: date | None = None
    cleared_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    party_id: int | None = Field(default=None, gt=0)
    status: ChequeStatus | None = None


class ChequeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    credit_account_id: int
    debit_account_id: int
    summary: str
    cheque_number: int
    issue_date: date
    cleared_date: date | None
    amount: Decimal
    party_id: int | None
    status: ChequeStatus
    created_at: datetime
    updated_at: datetime


class ChequeListResponse(BaseModel):
    cheques: list[ChequeOut]


class ChequeFilterOption(BaseModel):
    id: int | None
    name: str


class ChequeFilterOptionsResponse(BaseModel):
    parties: list[ChequeFilterOption]
    credit_accounts: list[ChequeFilterOption]
    debit_accounts: list[ChequeFilterOption]


ChequeIncrementUnit = Literal["days", "weeks", "months"]


class ChequeSeriesSchedule(BaseModel):
    increment_unit: ChequeIncrementUnit
    increment_n: int = Field(gt=0)
    count: int | None = Field(default=None, ge=1)
    end_date: date | None = None

    @model_validator(mode="after")
    def exactly_one_terminator(self) -> "ChequeSeriesSchedule":
        if (self.count is None) == (self.end_date is None):
            raise ValueError("provide exactly one of count or end_date")
        return self


class ChequeSeriesCreate(BaseModel):
    credit_account_id: int = Field(gt=0)
    debit_account_id: int = Field(gt=0)
    summary: str = Field(min_length=1, max_length=200)
    starting_cheque_number: int = Field(gt=0)
    starting_issue_date: date
    amount: Decimal = Field(gt=0)
    party_id: int | None = Field(default=None, gt=0)
    schedule: ChequeSeriesSchedule


class ChequeSeriesPreviewRow(BaseModel):
    cheque_number: int
    issue_date: date
    amount: Decimal
    number_conflict: bool = False


class ChequeSeriesPreviewOut(BaseModel):
    rows: list[ChequeSeriesPreviewRow]
    series_count: int
    max_allowed: int


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


AccrualPlanSettlementStatus = Literal[
    "any", "unsettled", "open", "partially_settled", "settled"
]


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
    has_settlement_allocations: bool = False


class AccrualPlanListFilterOptions(BaseModel):
    """Distinct ids used on ≥1 accrual plan — for register filter dropdowns (#168)."""

    party_ids: list[int] = Field(default_factory=list)
    target_account_ids: list[int] = Field(default_factory=list)
    bridge_account_ids: list[int] = Field(default_factory=list)


class AccrualPlanListResponse(BaseModel):
    plans: list[AccrualPlanOut]
    filter_options: AccrualPlanListFilterOptions | None = None


class AccrualPlanSummaryRollups(BaseModel):
    """Plan-level totals for the read-only view modal (#159, #169)."""

    total_original_accrued: Decimal
    total_settled_to_date: Decimal
    past_due: Decimal
    not_yet_due: Decimal
    unearned: Decimal


class AccrualPlanDetailResponse(BaseModel):
    plan: AccrualPlanOut
    obligations: list["AccrualObligationOut"]
    summary: AccrualPlanSummaryRollups


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
    default_cheque_credit_account_id: int | None = Field(default=None, gt=0)
    default_cheque_debit_account_id: int | None = Field(default=None, gt=0)
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
    default_cheque_credit_account_id: int | None
    default_cheque_debit_account_id: int | None
    max_attachment_upload_bytes: int
    max_cheque_series_count: int
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
    entry_id: int
    allocation_ids: list[int]
    allocated_amount: Decimal
    unapplied_amount: Decimal


class SettlementPreviewAllocationOut(BaseModel):
    obligation_id: int
    accrual_date: date | None
    source_entry_summary: str | None = None
    open_amount: Decimal
    applied_amount: Decimal
    settlement_type: SettlementType


class JournalEntrySettlementPreviewOut(BaseModel):
    party_id: int
    party_name: str
    lines: list[JournalLineIn]
    allocations: list[SettlementPreviewAllocationOut]
    receipt_cash_amount: Decimal | None = None
    payment_cash_amount: Decimal | None = None


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


BalanceSheetSection = Literal["assets", "liabilities", "equity"]


class BalanceSheetPeriodEcho(BaseModel):
    as_of_date: date


class BalanceSheetAccountRowOut(BaseModel):
    account_id: int | None = Field(
        default=None,
        description="Null when this row is system-computed (not a ledger account).",
    )
    account_name: str
    account_type: Literal["asset", "liability", "equity", "computed_equity"]
    is_active: bool | None = Field(
        default=None,
        description="Null when this row is system-computed.",
    )
    is_computed: bool = False
    amount: Decimal


class BalanceSheetSectionOut(BaseModel):
    section: BalanceSheetSection
    label: str
    accounts: list[BalanceSheetAccountRowOut]
    total: Decimal


class BalanceSheetBalanceCheckOut(BaseModel):
    assets_total: Decimal
    liabilities_total: Decimal
    equity_total: Decimal
    liabilities_plus_equity: Decimal
    is_balanced: bool
    difference: Decimal


class BalanceSheetReportOut(BaseModel):
    """Stable JSON contract for the Balance Sheet report (schema version 1)."""

    report_schema_version: Literal[1] = 1
    period: BalanceSheetPeriodEcho
    currency_label: str
    preset: Literal["today", "prior_year_end"] | None = None
    exclude_requires_review: bool
    assets: BalanceSheetSectionOut
    liabilities: BalanceSheetSectionOut
    equity: BalanceSheetSectionOut
    balance_check: BalanceSheetBalanceCheckOut
