"""Pure billing and penalty rules (Phase 5, Slice 2). No Django, no database.

These implement the decisions recorded for Slice 2 (see README_PHASE5_SLICE2.md, section 4):

* Penalty base: the REMAINING UNPAID amount of each overdue bill. Never negative. Zero is never penalised.
* Overdue bill: an active regular bill whose remaining unpaid amount is at least PAID_EPSILON and whose billing
  period is earlier than the consumer's latest billed period.
* Penalty counter: the number of CONSECUTIVE unpaid monthly periods, counted backwards from the most recent
  overdue period. It is derived from the records each time; it is never incremented by saving a reading.
  It resets to zero as soon as the most recent overdue period is paid, or there is none.
* Threshold: a penalty is assessed when the counter is at least penalty_after (the configured months).
* Each overdue bill is penalised at most once (enforced by a unique key on penalty_charge.bill_id).
* Exempt accounts are never penalised (enforced by the service).

PAID_EPSILON is half a centavo. Amounts below it are treated as paid. It only absorbs binary floating-point
residue from adding DOUBLE values; it is not a business rate.
"""

PAID_EPSILON = 0.005


def period_index(year, month):
    """A single integer per billing month, so periods can be compared and stepped backwards."""
    return int(year) * 12 + (int(month) - 1)


def is_unpaid(remaining):
    return remaining is not None and remaining >= PAID_EPSILON


def overdue_run(billed):
    """billed: dict period_index -> remaining unpaid, for every active regular bill of one consumer.

    Returns the list of period indexes that form the current run of consecutive unpaid overdue periods, most
    recent first. An empty list means the counter is zero.
    """
    if not billed:
        return []
    latest = max(billed)
    overdue = [p for p in billed if p < latest]
    if not overdue:
        return []
    run = []
    p = max(overdue)
    while p in billed and is_unpaid(billed[p]):
        run.append(p)
        p -= 1
    return run


def penalty_due(counter, threshold):
    """True when the counter has reached the configured threshold (penalty_after, in months)."""
    if threshold is None:
        return False
    return counter >= threshold


def penalty_amount(rate_percent, base):
    """rate_percent × base ÷ 100, for a positive base only. Zero or negative results are never charged."""
    if base is None or base < PAID_EPSILON:
        return 0.0
    if rate_percent is None or rate_percent <= 0:
        return 0.0
    return float(rate_percent) * float(base) / 100.0


def tariff_regime(year, month):
    """Which tariff regime applies to a billing period. Boundaries copied from wb_core.services.tariff.bill_compute."""
    p = period_index(year, month)
    if p >= period_index(2026, 1):
        return "progressive_x0.70"
    if p >= period_index(2024, 10):
        return "progressive_x0.60"
    return "linear_consumer_type"


def correction_difference(old_amount, new_amount):
    return float(new_amount or 0.0) - float(old_amount or 0.0)
