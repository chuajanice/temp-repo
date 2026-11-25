"""Meter readings, monthly bills and penalty charges (SQL sections 3 and 4).

Generated unique keys (active_bill_key, active_reading_key) and the matching unique
constraints are enforced by MySQL only. They are not declared on the models because Django
would try to write the generated columns on INSERT.
"""
from django.db import models


class MeterReading(models.Model):
    meter_reading_id = models.BigAutoField(primary_key=True)
    connection = models.ForeignKey("Connection", db_column="consumer_id", on_delete=models.PROTECT, related_name="meter_readings")
    billing_year = models.IntegerField()
    billing_month = models.PositiveSmallIntegerField()
    reading_kind = models.CharField(max_length=10, choices=[("regular", "regular"), ("reset", "reset"), ("issue_flag", "issue_flag")])
    status = models.CharField(max_length=20, choices=[("active", "active"), ("pending_review", "pending_review"), ("superseded", "superseded")], default="active")
    reading_value = models.IntegerField(null=True, blank=True)
    previous_reading = models.IntegerField(null=True, blank=True)
    consumption = models.IntegerField(null=True, blank=True)
    recorded_by = models.CharField(max_length=50, null=True, blank=True)
    recorded_on = models.DateField(null=True, blank=True)
    legacy_transaction_id = models.IntegerField(null=True, blank=True, unique=True)

    class Meta:
        managed = False
        db_table = "meter_reading"
        indexes = [models.Index(fields=["connection", "billing_year", "billing_month"], name="ix_reading_latest")]
        constraints = [
            models.CheckConstraint(check=models.Q(billing_month__gte=1, billing_month__lte=12), name="chk_reading_month"),
        ]


class Bill(models.Model):
    bill_id = models.BigAutoField(primary_key=True)
    connection = models.ForeignKey("Connection", db_column="consumer_id", on_delete=models.PROTECT, related_name="bills")
    billing_year = models.IntegerField()
    billing_month = models.PositiveSmallIntegerField()
    meter_reading = models.ForeignKey("MeterReading", db_column="meter_reading_id", null=True, blank=True, on_delete=models.PROTECT, related_name="bills")
    tariff_schedule = models.ForeignKey("TariffSchedule", db_column="tariff_schedule_id", null=True, blank=True, on_delete=models.PROTECT, related_name="bills")
    consumer_type = models.ForeignKey("ConsumerType", db_column="consumer_type_code", null=True, blank=True, on_delete=models.PROTECT, related_name="bills")
    bill_amount = models.FloatField(null=True, blank=True)
    previous_bill_amount = models.FloatField(null=True, blank=True)
    amount_due = models.FloatField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    months_not_paid = models.IntegerField(default=0)
    is_excess_extracted = models.BooleanField(default=False)
    remarks = models.TextField(null=True, blank=True)
    processed_by = models.CharField(max_length=50, null=True, blank=True)
    billed_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[("active", "active"), ("pending_review", "pending_review"), ("superseded", "superseded")], default="active")
    legacy_transaction_id = models.IntegerField(null=True, blank=True, unique=True)
    tariff_snapshot = models.JSONField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "bill"
        indexes = [models.Index(fields=["connection", "is_paid", "billing_year", "billing_month"], name="ix_bill_unpaid")]
        constraints = [
            models.CheckConstraint(check=models.Q(billing_month__gte=1, billing_month__lte=12), name="chk_bill_month"),
            models.CheckConstraint(check=models.Q(is_paid__in=[0, 1]), name="chk_bill_paid"),
        ]


class PenaltyCharge(models.Model):
    penalty_charge_id = models.BigAutoField(primary_key=True)
    connection = models.ForeignKey("Connection", db_column="consumer_id", on_delete=models.PROTECT, related_name="penalty_charges")
    billing_year = models.IntegerField()
    billing_month = models.PositiveSmallIntegerField()
    penalty_rule = models.ForeignKey("PenaltyRule", db_column="penalty_rule_id", null=True, blank=True, on_delete=models.PROTECT, related_name="penalty_charges")
    basis_used = models.CharField(max_length=30, choices=[("percent_of_ytd_unpaid", "percent_of_ytd_unpaid"), ("percent_of_bill", "percent_of_bill"), ("fixed_amount", "fixed_amount"), ("legacy_unknown", "legacy_unknown"), ("remaining_unpaid", "remaining_unpaid")])
    base_amount = models.FloatField(null=True, blank=True)
    rate_used = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    amount = models.FloatField()
    charge_source = models.CharField(max_length=10, choices=[("system", "system"), ("manual", "manual")])
    processed_by = models.CharField(max_length=50, null=True, blank=True)
    charged_on = models.DateField(null=True, blank=True)
    legacy_transaction_id = models.IntegerField(null=True, blank=True, unique=True)
    # One penalty per overdue bill (Phase 5 Slice 2). Unique in the database as well.
    bill = models.ForeignKey("Bill", db_column="bill_id", null=True, blank=True, unique=True,
                             on_delete=models.PROTECT, related_name="penalty_assessment")

    class Meta:
        managed = False
        db_table = "penalty_charge"
        indexes = [models.Index(fields=["connection", "billing_year", "billing_month"], name="ix_penalty_period")]
        constraints = [
            models.CheckConstraint(check=models.Q(billing_month__gte=1, billing_month__lte=12), name="chk_penalty_month"),
        ]
