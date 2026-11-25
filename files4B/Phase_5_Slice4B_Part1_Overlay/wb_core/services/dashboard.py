"""Dashboard and meter-reading list helpers on the normalized database (Phase 5, Slice 4B). Read only.

The legacy dashboard shows consumers with the amount of their unpaid bills. The normalized amount is the REMAINING
unpaid amount of each unpaid bill. Legacy added the full bill amount of every bill with the unpaid flag, so a partly
paid bill was overstated. This is the one deliberate change to the dashboard figure (see README_PHASE5_SLICE4B.md).
"""

import math

from wb_core.models import BarangayMonthlySummary
from wb_core.services import billing_rules as rules
from wb_core.services.billing import _billed_remaining

NORMALIZED = "normalized"


def unpaid_billing_total(connection_id):
    remaining, _ = _billed_remaining(connection_id)
    return math.fsum(v for v in remaining.values() if rules.is_unpaid(v))


def summary_years():
    return sorted(set(BarangayMonthlySummary.objects.using(NORMALIZED).values_list("billing_year", flat=True)))
