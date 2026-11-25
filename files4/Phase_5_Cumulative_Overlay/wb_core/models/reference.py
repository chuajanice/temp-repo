"""Reference and configuration tables (SQL sections 1 and 8).

All classes are unmanaged: the tables are created from wb_core/sql/normalized_schema_v3.sql
by the wb_core migration. Keep field definitions in step with the DDL; the static tests in
wb_core/tests/test_static_models.py compare them.
"""
from django.db import models


class Barangay(models.Model):
    barangay_id = models.BigAutoField(primary_key=True)
    legacy_barangay_id = models.BigIntegerField(null=True, blank=True, unique=True)
    name = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = "barangay"


class ConsumerType(models.Model):
    consumer_type_code = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=20)
    min_reading_m3 = models.IntegerField()
    min_reading_charge = models.DecimalField(max_digits=12, decimal_places=2)
    rate_after_min = models.DecimalField(max_digits=12, decimal_places=2)
    created_on = models.DateField()
    modified_on = models.DateField()
    created_by = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "consumer_type"


class TariffSchedule(models.Model):
    tariff_schedule_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100)
    method = models.CharField(max_length=20, choices=[("consumer_type_linear", "consumer_type_linear"), ("progressive_tiers", "progressive_tiers")])
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    adjustment_factor = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    source_note = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tariff_schedule"
        indexes = [models.Index(fields=["effective_from"], name="ix_tariff_effective")]
        constraints = [
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True) | models.Q(effective_to__gt=models.F("effective_from")),
                name="chk_tariff_period",
            ),
        ]


class TariffTier(models.Model):
    tariff_tier_id = models.BigAutoField(primary_key=True)
    tariff_schedule = models.ForeignKey("TariffSchedule", db_column="tariff_schedule_id", on_delete=models.PROTECT, related_name="tariff_tiers")
    tier_no = models.IntegerField()
    from_m3 = models.IntegerField()
    to_m3 = models.IntegerField(null=True, blank=True)
    rate_per_m3 = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        managed = False
        db_table = "tariff_tier"
        unique_together = [("tariff_schedule", "tier_no")]
        constraints = [
            models.CheckConstraint(
                check=models.Q(from_m3__gte=1) & (models.Q(to_m3__isnull=True) | models.Q(to_m3__gte=models.F("from_m3"))),
                name="chk_tier_range",
            ),
        ]


class PenaltyCode(models.Model):
    penalty_code = models.CharField(max_length=20, primary_key=True)
    penalty_after_months = models.IntegerField(default=0)
    days_applied_after = models.IntegerField(default=0)
    penalty_info = models.TextField(null=True, blank=True)
    created_on = models.DateField(null=True, blank=True)
    created_by = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "penalty_code"


class PenaltyRule(models.Model):
    penalty_rule_id = models.BigAutoField(primary_key=True)
    penalty_code = models.ForeignKey("PenaltyCode", db_column="penalty_code", on_delete=models.PROTECT, related_name="penalty_rules")
    basis = models.CharField(max_length=21, choices=[("percent_of_ytd_unpaid", "percent_of_ytd_unpaid"), ("percent_of_bill", "percent_of_bill"), ("fixed_amount", "fixed_amount"), ("remaining_unpaid", "remaining_unpaid")])
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    unit_status = models.CharField(max_length=20, choices=[("confirmed", "confirmed"), ("unconfirmed", "unconfirmed")], default="unconfirmed")
    source_note = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "penalty_rule"
        indexes = [models.Index(fields=["penalty_code", "effective_from"], name="ix_penalty_rule_code")]


class DiscountCode(models.Model):
    discount_code = models.CharField(max_length=20, primary_key=True)
    discount_percent = models.IntegerField()
    created_on = models.DateField()
    created_by = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "discount_code"


class BillingPolicy(models.Model):
    billing_policy_id = models.AutoField(primary_key=True)
    allocation_policy = models.CharField(max_length=20, choices=[("manual_selection", "manual_selection"), ("fifo", "fifo")], default="manual_selection")
    rounding_mode = models.CharField(max_length=20, choices=[("legacy_unrounded", "legacy_unrounded"), ("half_up_2dp", "half_up_2dp")], default="legacy_unrounded")
    effective_from = models.DateField()

    class Meta:
        managed = False
        db_table = "billing_policy"


class SystemSetting(models.Model):
    system_setting_id = models.BigAutoField(primary_key=True)
    current_year = models.IntegerField()
    current_month = models.IntegerField()
    authors = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = "system_setting"
        constraints = [
            models.CheckConstraint(check=models.Q(current_month__gte=1, current_month__lte=12), name="chk_setting_month"),
        ]


class RevenueSetting(models.Model):
    """Legacy index_revenuecode, kept in full. No live code reads it (decision D-1)."""
    revenue_setting_id = models.BigAutoField(primary_key=True)
    application_fee = models.FloatField(default=0)
    mayors_permit = models.FloatField(default=0)
    gravel_excavation = models.FloatField(default=0)
    asphalted_road = models.FloatField(default=0)
    cemented_road = models.FloatField(default=0)
    additionalfee_pipe_of_20_lineal_feet = models.FloatField(default=0)
    residentialservice_per_month = models.FloatField(default=0)
    commercialservice_per_month = models.FloatField(default=0)
    residentialservice_excess_per_cubicmeter = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commercialservice_excess_per_cubicmeter = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    drilling_from_mainline = models.FloatField(default=0)
    reinstallation_fee = models.FloatField(default=0)
    tapping_fee = models.FloatField(default=0)
    repair_fee = models.FloatField(default=0)
    transfer_fee = models.FloatField(default=0)
    three_month_penalty = models.FloatField(default=0)
    send_disconnection_notice_after = models.IntegerField(default=0)
    disconnection_after = models.IntegerField(default=0)
    penalty_after = models.IntegerField(default=0)
    fix_amount_penalty = models.FloatField(default=0)
    percentage_penalty = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    class Meta:
        managed = False
        db_table = "revenue_setting"
