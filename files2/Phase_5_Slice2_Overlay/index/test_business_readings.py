"""Phase 5 Slice 2 behavioural tests (readings, bills, penalties, corrections). NOT EXECUTED IN THE BUILD SANDBOX.

Run on the development PC:
    python manage.py test index.test_business_readings

Uses Django's temporary test databases only. Never touches waterbillingv3.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from index.models import ConsumerInfo, SystemUsers
from wb_core.models import (Barangay, Bill, BillCorrection, Connection, ConsumerType, Customer, Meter,
                            MeterReading, PaymentAllocation, PenaltyCharge, PenaltyCode, PenaltyRule)
from wb_core.services import billing as svc
from wb_core.services.tariff import RateTerms, bill_compute

TODAY = date(2026, 3, 15)
N = "normalized"


def _connection(cid="0000000001-01", exempt=False):
    customer = Customer.objects.using(N).create(first_name="Ana", middle_name="", last_name="Cruz",
                                                birth_date=date(1980, 1, 1), sex="FEMALE", email="",
                                                mobile_number="")
    meter = Meter.objects.using(N).create(meter_number="M-%s" % cid[-6:])
    return Connection.objects.using(N).create(
        consumer_id=cid, customer=customer, meter=meter, barangay=Barangay.objects.using(N).get(legacy_barangay_id=1),
        consumer_type=ConsumerType.objects.using(N).get(pk="RES"), penalty_code=PenaltyCode.objects.using(N).get(pk="P001"),
        home_address="Purok 1", sitio="", initial_meter_reading=0, status=1, is_stopped=False, is_deleted=False,
        is_disconnected=False, is_exempt=exempt, penalty_counter=0, date_added=TODAY, cached_current_reading=0,
        cached_current_balance=0.0, cached_excess=0.0, cached_cumulative=0.0)


class SliceTwoBase(TestCase):
    databases = {"default", "normalized"}

    @classmethod
    def setUpTestData(cls):
        Barangay.objects.using(N).create(name="Poblacion", legacy_barangay_id=1)
        ConsumerType.objects.using(N).create(consumer_type_code="RES", name="Residential", min_reading_m3=5,
                                             min_reading_charge=Decimal("75.00"), rate_after_min=Decimal("10.00"),
                                             created_on=date(2026, 1, 1), modified_on=date(2026, 1, 1))
        PenaltyCode.objects.using(N).create(penalty_code="P001", penalty_after_months=1, days_applied_after=0)
        PenaltyRule.objects.using(N).create(penalty_code_id="P001", basis="remaining_unpaid", rate=Decimal("2.0000"),
                                            effective_from=date(2026, 1, 1), unit_status="confirmed")

    def expected(self, year, month, usage):
        return float(bill_compute(year, month, usage, RateTerms(5, 75.0, 10.0)))


class ReadingAndBillTests(SliceTwoBase):

    def test_first_reading_creates_reading_bill_snapshot_and_balance(self):
        c = _connection()
        result = svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        self.assertEqual(result.usage, 100)
        self.assertEqual(result.amount, self.expected(2026, 1, 100))
        bill = Bill.objects.using(N).get(connection=c)
        self.assertEqual(bill.tariff_snapshot["regime"], "progressive_x0.70")
        self.assertEqual(bill.tariff_snapshot["min_reading_m3"], 5)
        self.assertEqual(bill.processed_by, "teller1")
        c.refresh_from_db(using=N)
        self.assertEqual(c.cached_current_reading, 100)
        self.assertEqual(c.cached_current_balance, self.expected(2026, 1, 100))

    def test_second_reading_for_the_same_period_is_refused_and_changes_nothing(self):
        c = _connection()
        svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        with self.assertRaises(svc.ReadingAlreadyRecorded):
            svc.record_reading(c.pk, 2026, 1, 150, "teller1", today=TODAY)
        self.assertEqual(MeterReading.objects.using(N).filter(connection=c, reading_kind="regular").count(), 1)
        self.assertEqual(Bill.objects.using(N).filter(connection=c).count(), 1)

    def test_exempt_account_gets_a_zero_bill_and_no_penalty(self):
        c = _connection(exempt=True)
        result = svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        self.assertEqual(result.amount, 0.0)
        self.assertEqual(PenaltyCharge.objects.using(N).filter(connection=c).count(), 0)

    def test_unexpected_error_rolls_back_the_whole_reading(self):
        c = _connection()
        svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        with mock.patch.object(svc, "assess_penalties", side_effect=RuntimeError("disk on fire")):
            with self.assertRaises(RuntimeError):
                svc.record_reading(c.pk, 2026, 2, 180, "teller1", today=TODAY)
        self.assertFalse(MeterReading.objects.using(N).filter(connection=c, billing_month=2).exists())
        self.assertFalse(Bill.objects.using(N).filter(connection=c, billing_month=2).exists())


class PenaltyTests(SliceTwoBase):

    def _jan_unpaid_then_feb(self):
        c = _connection()
        svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        jan = Bill.objects.using(N).get(connection=c, billing_month=1)
        result = svc.record_reading(c.pk, 2026, 2, 180, "teller1", today=TODAY)
        return c, jan, result

    def test_penalty_is_the_rate_times_the_remaining_unpaid_amount_of_the_overdue_bill(self):
        c, jan, result = self._jan_unpaid_then_feb()
        self.assertEqual(result.penalties_assessed, 1)
        pen = PenaltyCharge.objects.using(N).get(connection=c)
        self.assertEqual(pen.bill_id, jan.pk)
        self.assertAlmostEqual(pen.amount, 2.0 * jan.bill_amount / 100.0, places=9)
        self.assertEqual(pen.basis_used, "remaining_unpaid")

    def test_penalty_is_not_duplicated_when_assessed_again(self):
        c, jan, _ = self._jan_unpaid_then_feb()
        c.refresh_from_db(using=N)
        svc.assess_penalties(c, "teller1", TODAY)
        svc.assess_penalties(c, "teller1", TODAY)
        self.assertEqual(PenaltyCharge.objects.using(N).filter(connection=c).count(), 1)

    def test_counter_is_derived_not_incremented_by_saves(self):
        c, jan, _ = self._jan_unpaid_then_feb()
        c.refresh_from_db(using=N)
        for _ in range(3):
            svc.assess_penalties(c, "teller1", TODAY)
        c.refresh_from_db(using=N)
        self.assertEqual(c.penalty_counter, 1)

    def test_counter_resets_when_the_overdue_bill_is_paid(self):
        c, jan, _ = self._jan_unpaid_then_feb()
        PaymentAllocation.objects.using(N).create(connection=c, billing_year=2026, billing_month=1,
                                                  amount_applied=jan.bill_amount, applied_on=TODAY,
                                                  processed_by="teller1")
        c.refresh_from_db(using=N)
        svc.assess_penalties(c, "teller1", TODAY)
        c.refresh_from_db(using=N)
        self.assertEqual(c.penalty_counter, 0)

    def test_overpayment_never_produces_a_penalty(self):
        c = _connection()
        svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        jan = Bill.objects.using(N).get(connection=c, billing_month=1)
        PaymentAllocation.objects.using(N).create(connection=c, billing_year=2026, billing_month=1,
                                                  amount_applied=jan.bill_amount + 50.0, applied_on=TODAY,
                                                  processed_by="teller1")
        result = svc.record_reading(c.pk, 2026, 2, 180, "teller1", today=TODAY)
        self.assertEqual(result.penalties_assessed, 0)
        self.assertFalse(PenaltyCharge.objects.using(N).filter(connection=c).exists())

    def test_missing_confirmed_rule_refuses_the_reading_and_saves_nothing(self):
        c = _connection()
        svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        PenaltyRule.objects.using(N).update(unit_status="unconfirmed")
        with self.assertRaises(svc.PenaltyRuleNotConfigured):
            svc.record_reading(c.pk, 2026, 2, 180, "teller1", today=TODAY)
        self.assertFalse(Bill.objects.using(N).filter(connection=c, billing_month=2).exists())
        self.assertFalse(MeterReading.objects.using(N).filter(connection=c, billing_month=2).exists())


@override_settings(WB_BUSINESS_DB="normalized")
class CorrectionTests(SliceTwoBase):

    def _issued(self):
        c = _connection()
        svc.record_reading(c.pk, 2026, 1, 100, "teller1", today=TODAY)
        return c, Bill.objects.using(N).get(connection=c, billing_month=1)

    def test_non_administrator_cannot_correct(self):
        c, _ = self._issued()
        with self.assertRaises(svc.CorrectionNotAllowed):
            svc.correct_reading(c.pk, 2026, 1, 120, "wrong reason", "teller1", is_admin=False, today=TODAY)
        self.assertEqual(BillCorrection.objects.using(N).count(), 0)

    def test_reason_is_mandatory(self):
        c, _ = self._issued()
        with self.assertRaises(svc.CorrectionNotAllowed):
            svc.correct_reading(c.pk, 2026, 1, 120, "   ", "admin1", is_admin=True, today=TODAY)

    def test_correction_supersedes_the_bill_and_keeps_the_original(self):
        c, old = self._issued()
        result = svc.correct_reading(c.pk, 2026, 1, 120, "Meter misread at source", "admin1", is_admin=True, today=TODAY)
        old.refresh_from_db(using=N)
        self.assertEqual(old.status, "superseded")
        self.assertEqual(old.bill_amount, self.expected(2026, 1, 100))
        new = Bill.objects.using(N).get(connection=c, billing_month=1, status="active")
        self.assertEqual(new.bill_amount, self.expected(2026, 1, 120))
        row = BillCorrection.objects.using(N).get()
        self.assertEqual(row.superseded_bill_id, old.pk)
        self.assertEqual(row.corrected_bill_id, new.pk)
        self.assertEqual(row.old_reading, 100)
        self.assertEqual(row.new_reading, 120)
        self.assertAlmostEqual(row.difference, new.bill_amount - old.bill_amount, places=9)
        self.assertEqual(row.performed_by, "admin1")
        self.assertEqual(row.reason, "Meter misread at source")

    def test_correction_uses_the_original_tariff_snapshot(self):
        c, _ = self._issued()
        ConsumerType.objects.using(N).filter(pk="RES").update(rate_after_min=Decimal("99.00"))
        svc.correct_reading(c.pk, 2026, 1, 120, "Meter misread", "admin1", is_admin=True, today=TODAY)
        new = Bill.objects.using(N).get(connection=c, billing_month=1, status="active")
        self.assertEqual(new.bill_amount, self.expected(2026, 1, 120))

    def test_payments_are_untouched_and_the_remaining_balance_is_recomputed_by_period(self):
        c, old = self._issued()
        alloc = PaymentAllocation.objects.using(N).create(connection=c, billing_year=2026, billing_month=1,
                                                          amount_applied=80.0, applied_on=TODAY, processed_by="teller1")
        svc.correct_reading(c.pk, 2026, 1, 120, "Meter misread", "admin1", is_admin=True, today=TODAY)
        alloc.refresh_from_db(using=N)
        self.assertEqual(alloc.amount_applied, 80.0)
        self.assertEqual(PaymentAllocation.objects.using(N).filter(connection=c).count(), 1)
        new = Bill.objects.using(N).get(connection=c, billing_month=1, status="active")
        remaining = new.bill_amount - svc._allocated(c.pk, 2026, 1)
        self.assertAlmostEqual(remaining, self.expected(2026, 1, 120) - 80.0, places=9)

    def test_a_bill_can_be_corrected_only_once(self):
        c, _ = self._issued()
        svc.correct_reading(c.pk, 2026, 1, 120, "Meter misread", "admin1", is_admin=True, today=TODAY)
        with self.assertRaises(svc.BillingError):
            svc.correct_reading(c.pk, 2026, 1, 130, "Again", "admin1", is_admin=True, today=TODAY)
        self.assertEqual(BillCorrection.objects.using(N).count(), 1)

    def test_correction_never_assesses_a_penalty(self):
        c, jan = self._issued()
        svc.record_reading(c.pk, 2026, 2, 180, "teller1", today=TODAY)
        before = PenaltyCharge.objects.using(N).filter(connection=c).count()
        svc.correct_reading(c.pk, 2026, 1, 120, "Meter misread", "admin1", is_admin=True, today=TODAY)
        self.assertEqual(PenaltyCharge.objects.using(N).filter(connection=c).count(), before)


@override_settings(WB_BUSINESS_DB="normalized")
class RoutingGuardTests(SliceTwoBase):

    def _login_teller(self):
        user = SystemUsers.objects.create(username="teller9", profilepic=None, authorizedapprover="x", is_teller=True)
        user.set_password("test-only-password")
        user.save()
        self.client.force_login(user)

    def test_reading_screen_post_saves_to_the_normalized_database(self):
        c = _connection("0000000002-01")
        self._login_teller()
        url = reverse("inputreading", kwargs={"id": c.consumer_id, "year": 2026})
        response = self.client.post(url, {"reading-January": "100"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Bill.objects.using(N).filter(connection=c, billing_month=1).exists())
        self.assertEqual(ConsumerInfo.objects.count(), 0)

    def test_unmigrated_route_is_refused_and_writes_nothing_to_legacy(self):
        self._login_teller()
        response = self.client.get(reverse("stopmeter", kwargs={"id": "0000000002-01"}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("consumer_list"))
        self.assertEqual(ConsumerInfo.objects.count(), 0)
