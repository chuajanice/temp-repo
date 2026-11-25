"""Reading corrections (Phase 5 Slice 2). Append-only: the application never updates or deletes these rows.

A correction supersedes the original bill (status 'superseded'), creates a corrected bill, and records the change
here with the mandatory reason and the authorised administrator. Payments and allocations are not changed.
"""
from django.db import models


class BillCorrection(models.Model):
    correction_id = models.BigAutoField(primary_key=True)
    connection = models.ForeignKey("Connection", db_column="consumer_id", on_delete=models.PROTECT,
                                   related_name="bill_corrections")
    # unique=True: each superseded bill can be corrected once.
    superseded_bill = models.ForeignKey("Bill", db_column="superseded_bill_id", unique=True,
                                        on_delete=models.PROTECT, related_name="correction_as_superseded")
    corrected_bill = models.ForeignKey("Bill", db_column="corrected_bill_id", on_delete=models.PROTECT,
                                       related_name="correction_as_corrected")
    billing_year = models.IntegerField()
    billing_month = models.PositiveSmallIntegerField()
    old_reading = models.IntegerField(null=True, blank=True)
    new_reading = models.IntegerField()
    old_amount = models.FloatField(null=True, blank=True)
    new_amount = models.FloatField(null=True, blank=True)
    difference = models.FloatField()
    reason = models.CharField(max_length=500)
    performed_by = models.CharField(max_length=20)
    performed_on = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "bill_correction"
        indexes = [models.Index(fields=["connection", "billing_year", "billing_month"], name="ix_correction_period")]
        constraints = [
            models.CheckConstraint(check=models.Q(billing_month__gte=1, billing_month__lte=12), name="chk_correction_month"),
        ]
