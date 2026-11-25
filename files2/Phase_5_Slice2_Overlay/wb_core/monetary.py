"""Monetary storage policy (Phase 4A, approved decision OPTION A: FLOAT/DOUBLE for money).

Rules
  * Monetary amounts (bills, payments, receipts, fees, balances, totals ...) are Django FloatField and MySQL DOUBLE.
    This matches the precision of the legacy FloatField columns.
  * Tariff parameters, rates and percentages keep their existing DECIMAL types and precision.
  * All other numeric fields (counts, readings, usage, years, months, identifiers) are unchanged.
  * FLOAT/DOUBLE is NOT exact decimal arithmetic. Values are stored as the nearest binary double. Comparisons
    of money must use the documented procedure in wb_core/importer/reconcile.py, not ad-hoc tolerances.

This module is pure Python (no Django) so that tests can check the policy without a database.
"""

# (table, column) pairs that store money amounts. Verified against the v3 DDL by test_static_monetary.py.
MONEY_COLUMNS = (
    ("bill", "bill_amount"),
    ("bill", "previous_bill_amount"),
    ("bill", "amount_due"),
    ("penalty_charge", "base_amount"),
    ("penalty_charge", "amount"),
    ("fee_plan", "amount"),
    ("fee_plan", "remainder"),
    ("fee_charge", "amount"),
    ("fee_payment", "amount"),
    ("receipt", "amount_received"),
    ("discount_application", "discount_amount"),
    ("payment_allocation", "amount_applied"),
    ("excess_credit", "excess_amount"),
    ("partial_payment_log", "partial_amount"),
    ("unpaid_snapshot", "unpaid_amount"),
    ("connection", "cached_current_balance"),
    ("connection", "cached_excess"),
    ("connection", "cached_cumulative"),
    ("barangay_monthly_summary", "total_due"),
    ("barangay_monthly_summary", "total_paid"),
    ("revenue_setting", "application_fee"),
    ("revenue_setting", "mayors_permit"),
    ("revenue_setting", "gravel_excavation"),
    ("revenue_setting", "asphalted_road"),
    ("revenue_setting", "cemented_road"),
    ("revenue_setting", "additionalfee_pipe_of_20_lineal_feet"),
    ("revenue_setting", "residentialservice_per_month"),
    ("revenue_setting", "commercialservice_per_month"),
    ("revenue_setting", "drilling_from_mainline"),
    ("revenue_setting", "reinstallation_fee"),
    ("revenue_setting", "tapping_fee"),
    ("revenue_setting", "repair_fee"),
    ("revenue_setting", "transfer_fee"),
    ("revenue_setting", "three_month_penalty"),
    ("revenue_setting", "fix_amount_penalty"),
)

# Decimal columns that are NOT money. They are tariff parameters, per-unit rates or percentages.
# They keep DECIMAL exactly as before (Phase 4A instruction: keep tariff rates and percentage precision).
DECIMAL_NON_MONEY_COLUMNS = (
    ("consumer_type", "min_reading_charge"),     # tariff parameter (pesos for the minimum block)
    ("consumer_type", "rate_after_min"),         # tariff rate per cubic metre
    ("tariff_schedule", "adjustment_factor"),    # multiplier
    ("tariff_tier", "rate_per_m3"),              # tariff rate
    ("penalty_rule", "rate"),                    # percentage (or fixed amount for basis fixed_amount; see note)
    ("penalty_charge", "rate_used"),             # percentage used at the time of the charge
    ("revenue_setting", "residentialservice_excess_per_cubicmeter"),  # per-cubic-metre rate
    ("revenue_setting", "commercialservice_excess_per_cubicmeter"),   # per-cubic-metre rate
    ("revenue_setting", "percentage_penalty"),   # percentage
)

FLOAT_SQL_TYPE = "DOUBLE"
FLOAT_DJANGO_FIELD = "FloatField"
DECIMAL_DJANGO_FIELD = "DecimalField"


# Money columns added in Phase 5 Slice 2 (reading corrections). Also DOUBLE.
V5_MONEY_COLUMNS = (
    ("bill_correction", "old_amount"),
    ("bill_correction", "new_amount"),
    ("bill_correction", "difference"),
)


def is_money(table, column):
    return (table, column) in set(MONEY_COLUMNS) | set(V5_MONEY_COLUMNS)


def is_kept_decimal(table, column):
    return (table, column) in set(DECIMAL_NON_MONEY_COLUMNS)
