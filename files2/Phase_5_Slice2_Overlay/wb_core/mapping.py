"""Legacy-to-normalized mapping registry (Phase 2).

This file is DATA. It records how every legacy model in index/models.py maps to the
normalized models in wb_core/models. It contains no database access and no business logic.

Status values
  direct        legacy field copied to a normalized field (type may change, value does not)
  transform     value changes form (for example a name becomes a foreign key, or a value is stored as a different type)
  cache         normalized field is a stored snapshot that the services must keep up to date
  split         one legacy record becomes several normalized records (see MODEL_MAP)
  unmapped      no normalized equivalent. Reason is recorded; the adapter must not invent a value
  kept_legacy   stays in the legacy system on purpose (users, login records)

Tests in wb_core/tests/test_static_phase2.py check that every target named here really exists.
"""

# Model-level map: legacy class -> normalized targets and status.
MODEL_MAP = {
    "SystemUsers": {"status": "kept_legacy", "targets": [], "note": "Stays in index_systemusers. Normalized tables store usernames as text."},
    "LoginRec": {"status": "kept_legacy", "targets": [], "note": "Sign-in tracking. Not part of billing."},
    "ConsumerType": {"status": "direct", "targets": ["ConsumerType"], "note": "contypeid -> consumer_type_code; contype -> name."},
    "Penalty": {"status": "split", "targets": ["PenaltyCode", "PenaltyRule"], "note": "Code and months/days go to PenaltyCode. penalty_rate goes to PenaltyRule.rate with unit_status='unconfirmed' (decision D-10)."},
    "Discount": {"status": "direct", "targets": ["DiscountCode"], "note": "discount_rate (integer) -> discount_percent. Live payment code uses it as a percentage."},
    "Barangays": {"status": "direct", "targets": ["Barangay"], "note": "Legacy id -> legacy_barangay_id (kept for traceability). barangay -> name."},
    "BarangayRecord": {"status": "transform", "targets": ["BarangayMonthlySummary"], "note": "36 month columns (due/paid/usage x 12) become 12 rows per barangay and year."},
    "ConsumerInfo": {"status": "split", "targets": ["Customer", "Meter", "Connection"], "note": "Person fields go to Customer. meternumber goes to Meter. Account fields go to Connection."},
    "Transactions": {"status": "split", "targets": ["Bill", "MeterReading", "PenaltyCharge", "FeeCharge", "Receipt", "DiscountApplication", "PaymentAllocation"], "note": "One ledger table split by transType. See TRANSACTION_TYPE_MAP."},
    "Issues": {"status": "transform", "targets": ["Issue"], "note": "transactionid points to a Transactions row. It becomes meter_reading (issue flag) or bill (regular billing)."},
    "Messages": {"status": "transform", "targets": ["IssueMessage"], "note": "from_user and to_user (foreign keys to users) become from_username and to_username (text)."},
    "AdditionalFees": {"status": "direct", "targets": ["FeePlan"], "note": "amount and remainder are money: FloatField/DOUBLE (Phase 4A). remainder is an integer in legacy and is stored as a float. The M2M link to Transactions becomes FeeCharge rows (fee_links)."},
    "AdditionalFeesPayment": {"status": "direct", "targets": ["FeePayment"], "note": "addfeepayID is kept as legacy_addfeepay_id. The legacy save() builds it from fee id, month counter and time; the service must reproduce that format."},
    "SystemInfo": {"status": "direct", "targets": ["SystemSetting"], "note": "Year, month and authors."},
    "revenuecode": {"status": "direct", "targets": ["RevenueSetting"], "note": "Kept for completeness. No live code reads it (decision D-1)."},
    "ExcessLog": {"status": "direct", "targets": ["ExcessCredit"], "note": "excessID (a Transactions row) becomes receipt_id where it can be resolved. Otherwise it is kept as legacy_transaction_id."},
    "PartialLog": {"status": "direct", "targets": ["PartialPaymentLog"], "note": "Same rule as ExcessLog for partialID."},
    "UnpaidTransaction": {"status": "direct", "targets": ["UnpaidSnapshot"], "note": "consumer -> connection. unpaid_amount is money: float (DOUBLE)."},
}

# Transaction-type map for the single legacy ledger table (Phase 4B). Verified against wb_core/importer/rules.py.
# Each legacy row gets exactly one LegacyTransactionMap entry: imported with its target, or unmapped with an exception.
# Legacy transType (as written by the code) -> normalized target and the amount field used.
TRANSACTION_TYPE_MAP = {
    "Billing": {"target": "Bill (is_issue=False) or MeterReading (is_issue=True)", "amount": "bill", "in_balance": True},
    "Additional Fees": {"target": "FeeCharge", "amount": "bill", "in_balance": True},
    "Penalty": {"target": "PenaltyCharge", "amount": "bill", "in_balance": True},
    "Payment": {"target": "PaymentAllocation", "amount": "payment", "in_balance": True},
    "Discount": {"target": "DiscountApplication", "amount": "payment", "in_balance": True},
    "Received Amount": {"target": "Receipt", "amount": "receivedamt", "in_balance": False},
    "Reset Meter": {"target": "MeterReading (kind='reset')", "amount": None, "in_balance": False},
}

# Field-level map for ConsumerInfo (the fields the existing consumer screens use).
# Tuple: (legacy field, status, normalized target as "Model.field", note)
CONSUMERINFO_FIELDS = [
    ("consumer_id", "direct", "Connection.consumer_id", "Natural key, kept as is."),
    ("meternumber", "direct", "Meter.meter_number", "Reached through Connection.meter."),
    ("firstname", "direct", "Customer.first_name", ""),
    ("lastname", "direct", "Customer.last_name", ""),
    ("middlename", "direct", "Customer.middle_name", ""),
    ("homeaddress", "direct", "Connection.home_address", ""),
    ("installation_address", "transform", "Connection.barangay", "Legacy Barangays id becomes the Barangay row. The adapter returns legacy_barangay_id."),
    ("initialmeterreading", "direct", "Connection.initial_meter_reading", ""),
    ("contypeid", "transform", "Connection.consumer_type", "Foreign key by consumer_type_code."),
    ("status", "direct", "Connection.status", ""),
    ("penaltycounter", "direct", "Connection.penalty_counter", "Null allowed in both."),
    ("stopmeterflag", "direct", "Connection.is_stopped", ""),
    ("deleteflag", "direct", "Connection.is_deleted", "Soft delete. Rows are never physically removed."),
    ("disconnectionflag", "direct", "Connection.is_disconnected", ""),
    ("mobilenum", "direct", "Customer.mobile_number", ""),
    ("email", "direct", "Customer.email", ""),
    ("birthdate", "direct", "Customer.birth_date", ""),
    ("sex", "direct", "Customer.sex", ""),
    ("sitio", "direct", "Connection.sitio", ""),
    ("picture", "transform", "Customer.picture_path", "Legacy ImageField becomes a path string. Templates that call .url must be checked before any view switch (risk R-3)."),
    ("current_bal", "cache", "Connection.cached_current_balance", "Stored snapshot. Services recompute it. Money: float (DOUBLE)."),
    ("current_reading", "cache", "Connection.cached_current_reading", "Snapshot of the latest reading."),
    ("cummulative", "cache", "Connection.cached_cumulative", "Snapshot."),
    ("date_added", "direct", "Connection.date_added", ""),
    ("excess", "cache", "Connection.cached_excess", "Legacy integer becomes a float snapshot (money, DOUBLE)."),
    ("penaltycode", "transform", "Connection.penalty_code", "Legacy default 'POO1' is the model default. The normalized column is nullable."),
    ("first_tran", "cache", "Connection.first_transaction_year", "Year of the first transaction. Legacy 0 means none. Null is read as 0."),
    ("excep_accnt", "direct", "Connection.is_exempt", ""),
    ("has_additionalfees", "unmapped", None, "Declared in index/models.py but never read or written by the code. No normalized field is created."),
]

# Foreign-key targets that the adapter needs. Each name must exist in wb_core.models.
ADAPTER_TARGETS = [
    "Connection.consumer_id", "Connection.customer", "Connection.meter", "Connection.barangay",
    "Connection.consumer_type", "Connection.penalty_code", "Connection.home_address", "Connection.sitio",
    "Connection.initial_meter_reading", "Connection.status", "Connection.penalty_counter",
    "Connection.is_stopped", "Connection.is_deleted", "Connection.is_disconnected", "Connection.is_exempt",
    "Connection.date_added", "Connection.cached_current_balance", "Connection.cached_excess",
    "Connection.cached_cumulative", "Connection.cached_current_reading", "Connection.first_transaction_year",
    "Customer.first_name", "Customer.middle_name", "Customer.last_name", "Customer.mobile_number",
    "Customer.email", "Customer.birth_date", "Customer.sex", "Customer.picture_path",
    "Meter.meter_number", "Barangay.legacy_barangay_id", "Barangay.name",
]

# Risks found while mapping. Each needs a decision before the related view is switched.
RISKS = {
    "R-1": "Legacy ConsumerInfo.contypeid uses CASCADE. The normalized foreign key uses PROTECT. Deleting a consumer type would delete consumers in legacy and fail in normalized.",
    "R-2": "Legacy Transactions.discountcode is free text. Normalized DiscountApplication needs a valid DiscountCode row. Old codes that no longer exist cannot be linked.",
    "R-3": "ImageField is used as a file. Normalized stores a path string. Templates using .url are not yet checked.",
    "R-4": "Legacy get_balance adds every Billing row. Issue-flag rows are not bills in normalized. Parity depends on the legacy issue-flag bill value (blocker B3).",
    "R-5": "Legacy first_tran is a year, and 0 means none. Legacy order_by('year') may place NULL years first. The balance-independent yearly statistics must be re-checked.",
    "R-6": "AdditionalFeesPayment.addfeepayID is generated from the time in save(). Two payments in the same second collide (also true in legacy).",
    "R-7": "Money: legacy values are floats and the normalized money columns are DOUBLE (Phase 4A, approved OPTION A). FLOAT/DOUBLE is binary: it is not exact decimal arithmetic. Money is compared with exact digests (wb_core/reconcile rules), not tolerances.",
}

# Normalized models that have NO legacy source table. They hold configuration or audit data that
# the new system creates. Each one must still have a reason to exist.
NORMALIZED_ONLY = {
    "TariffSchedule": "Tariff periods. Seeded from the rules in index/functions.py (decision D-6).",
    "TariffTier": "Progressive bands for each tariff schedule. Seeded from rate_ranges.",
    "BillingPolicy": "Allocation policy (manual_selection by default) and rounding mode. No legacy equivalent.",
    "LegacyTransactionMap": "Traceability table written by the migration tool, one row per legacy Transactions row.",
    "MigrationException": "Records rows that the migration could not place. Written only by the migration tool.",
    "RemovedRecordAudit": "Copy of a row before the application removes it. Written at runtime (see P-1).",
    "BillCorrection": "Append-only record of a reading correction (Phase 5 Slice 2). Written by the correction service.",
}
