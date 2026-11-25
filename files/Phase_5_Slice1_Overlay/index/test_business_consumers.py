"""Phase 5 Slice 1 behavioural tests (customers, connections, meters). NOT EXECUTED IN THE BUILD SANDBOX
(no Django or MySQL there). Run on the development PC:

    python manage.py test index.test_business_consumers

Uses Django's temporary test databases only (test_<name> for each alias). Never touches waterbillingv3.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from index.models import SystemUsers
from wb_core.models import Barangay, Connection, ConsumerType, Customer, Meter, PenaltyCode


def _user(username, **roles):
    user = SystemUsers.objects.create(username=username, profilepic=None, authorizedapprover="x", **roles)
    user.set_password("test-only-password")
    user.save()
    return user


def _post_data(**overrides):
    data = {
        "isUpdate": "", "conid": "", "firstname": "Ana", "middlename": "", "lastname": "Cruz",
        "mobilenum": "09170000000", "email": "", "birthdate": "", "sex": "FEMALE", "sitio": "",
        "homeaddress": "Purok 1", "meternumber": "M-100", "initialmeterreading": "0",
        "installation_address": "1", "contypeid": "RES", "penaltycode": "",
    }
    data.update(overrides)
    return data


@override_settings(WB_BUSINESS_DB="normalized")
class NormalizedConsumerTests(TestCase):
    databases = {"default", "normalized"}

    @classmethod
    def setUpTestData(cls):
        cls.barangay = Barangay.objects.using("normalized").create(name="Poblacion", legacy_barangay_id=1)
        cls.ctype = ConsumerType.objects.using("normalized").create(
            consumer_type_code="RES", name="Residential", min_reading_m3=5,
            min_reading_charge=Decimal("75.00"), rate_after_min=Decimal("10.00"),
            created_on=date(2026, 1, 1), modified_on=date(2026, 1, 1))
        PenaltyCode.objects.using("normalized").create(penalty_code="P001")
        cls.teller = _user("teller1", is_teller=True)
        cls.reader = _user("reader1", is_reader=True)

    def _create(self, **overrides):
        self.client.force_login(self.teller)
        return self.client.post(reverse("consumercreation"), _post_data(**overrides))

    def test_list_renders_the_existing_template(self):
        self.client.force_login(self.teller)
        response = self.client.get(reverse("consumer_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "conlist.html")

    def test_create_writes_to_the_normalized_database_only(self):
        response = self._create()
        self.assertRedirects(response, reverse("consumer_list"))
        conn = Connection.objects.using("normalized").get()
        self.assertEqual(conn.consumer_id, "0000000001-01")
        self.assertEqual(conn.customer.last_name, "Cruz")
        self.assertEqual(conn.meter.meter_number, "M-100")
        self.assertEqual(conn.penalty_code_id, "P001")
        self.assertEqual(conn.status, 1)

    def test_second_create_gets_the_next_id(self):
        self._create()
        self._create(firstname="Ben", meternumber="M-101")
        ids = sorted(Connection.objects.using("normalized").values_list("consumer_id", flat=True))
        self.assertEqual(ids, ["0000000001-01", "0000000002-01"])

    def test_created_customer_appears_in_search(self):
        self._create()
        self.client.force_login(self.teller)
        response = self.client.get(reverse("consumer_list"), {"search": "Cruz"})
        self.assertContains(response, "Cruz")
        self.assertContains(response, "0000000001-01")

    def test_update_edits_the_same_account(self):
        self._create()
        self.client.force_login(self.teller)
        response = self.client.post(reverse("consumercreation"),
                                    _post_data(isUpdate="True", conid="0000000001-01", firstname="Anna"))
        self.assertRedirects(response, reverse("consumer_list"))
        self.assertEqual(Connection.objects.using("normalized").count(), 1)
        self.assertEqual(Customer.objects.using("normalized").get().first_name, "Anna")

    def test_failed_update_keeps_the_update_flag_so_a_retry_does_not_duplicate(self):
        self._create()
        self.client.force_login(self.teller)
        response = self.client.post(reverse("consumercreation"),
                                    _post_data(isUpdate="True", conid="0000000001-01", homeaddress=""))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["isUpdate"])
        self.assertEqual(Connection.objects.using("normalized").count(), 1)

    def test_edit_page_shows_the_saved_values(self):
        self._create()
        self.client.force_login(self.teller)
        response = self.client.get(reverse("consumerupdate", args=["0000000001-01"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["lastname"], "Cruz")
        self.assertEqual(response.context["form"].initial["meternumber"], "M-100")

    def test_missing_penalty_reference_is_reported_not_silently_defaulted(self):
        PenaltyCode.objects.using("normalized").filter(penalty_code="P001").delete()
        response = self._create()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("wb_init_reference" in e for e in response.context["form"].non_field_errors()))
        self.assertEqual(Connection.objects.using("normalized").count(), 0)

    def test_reader_is_redirected_away_from_the_consumer_list(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("consumer_list"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("bills_list"))

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("consumer_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response["Location"])


class LegacyModeIsUnchangedTests(TestCase):
    databases = {"default", "normalized"}

    @override_settings(WB_BUSINESS_DB="legacy")
    def test_default_mode_uses_the_existing_legacy_screen(self):
        user = _user("teller2", is_teller=True)
        self.client.force_login(user)
        response = self.client.get(reverse("consumer_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "conlist.html")
        self.assertEqual(Connection.objects.using("normalized").count(), 0)
