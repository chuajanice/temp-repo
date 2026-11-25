"""Normalized models for Water Billing System V4.

Import every model here so Django and the static tests see one flat namespace.
"""
from .reference import (  # noqa: F401
    Barangay, BillingPolicy, ConsumerType, DiscountCode, PenaltyCode, PenaltyRule,
    RevenueSetting, SystemSetting, TariffSchedule, TariffTier,
)
from .customers import Connection, Customer, Meter  # noqa: F401
from .readings_bills import Bill, MeterReading, PenaltyCharge  # noqa: F401
from .fees import FeeCharge, FeePayment, FeePlan  # noqa: F401
from .payments import (  # noqa: F401
    DiscountApplication, ExcessCredit, PartialPaymentLog, PaymentAllocation, Receipt, UnpaidSnapshot,
)
from .issues import Issue, IssueMessage  # noqa: F401
from .reporting_audit import (  # noqa: F401
    BarangayMonthlySummary, LegacyTransactionMap, MigrationException, RemovedRecordAudit,
)
from .corrections import BillCorrection  # noqa: F401

ALL_MODELS = (
    Barangay, ConsumerType, TariffSchedule, TariffTier, PenaltyCode, PenaltyRule, DiscountCode,
    BillingPolicy, SystemSetting, RevenueSetting, Customer, Meter, Connection, MeterReading, Bill,
    PenaltyCharge, FeePlan, FeeCharge, FeePayment, Receipt, DiscountApplication, PaymentAllocation,
    ExcessCredit, PartialPaymentLog, UnpaidSnapshot, Issue, IssueMessage, BarangayMonthlySummary,
    LegacyTransactionMap, MigrationException, RemovedRecordAudit, BillCorrection,
)
