"""Phase 5 Slice 2: billing, penalties per bill, tariff snapshot, and append-only reading corrections.

Additive only. Nothing is dropped, renamed, or converted. Money columns are DOUBLE (Phase 4 policy).
Hand-written to match wb_core/sql/normalized_schema_v5.sql and the Slice 2 models. Test:
wb_core/tests/test_static_slice2.py checks the statements against v5.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("wb_core", "0002_money_double"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="penaltyrule",
                    name="basis",
                    field=models.CharField(max_length=21, choices=[("percent_of_ytd_unpaid", "percent_of_ytd_unpaid"), ("percent_of_bill", "percent_of_bill"), ("fixed_amount", "fixed_amount"), ("remaining_unpaid", "remaining_unpaid")]),
                ),
                migrations.AlterField(
                    model_name="penaltycharge",
                    name="basis_used",
                    field=models.CharField(max_length=30, choices=[("percent_of_ytd_unpaid", "percent_of_ytd_unpaid"), ("percent_of_bill", "percent_of_bill"), ("fixed_amount", "fixed_amount"), ("legacy_unknown", "legacy_unknown"), ("remaining_unpaid", "remaining_unpaid")]),
                ),
                migrations.AddField(
                    model_name="bill",
                    name="tariff_snapshot",
                    field=models.JSONField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="penaltycharge",
                    name="bill",
                    field=models.ForeignKey(blank=True, db_column="bill_id", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="penalty_assessment", to="wb_core.bill", unique=True),
                ),
                migrations.CreateModel(
                    name="BillCorrection",
                    fields=[
                        ("correction_id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("billing_year", models.IntegerField()),
                        ("billing_month", models.PositiveSmallIntegerField()),
                        ("old_reading", models.IntegerField(blank=True, null=True)),
                        ("new_reading", models.IntegerField()),
                        ("old_amount", models.FloatField(blank=True, null=True)),
                        ("new_amount", models.FloatField(blank=True, null=True)),
                        ("difference", models.FloatField()),
                        ("reason", models.CharField(max_length=500)),
                        ("performed_by", models.CharField(max_length=20)),
                        ("performed_on", models.DateTimeField()),
                        ("connection", models.ForeignKey(db_column="consumer_id", on_delete=django.db.models.deletion.PROTECT, related_name="bill_corrections", to="wb_core.connection")),
                        ("superseded_bill", models.ForeignKey(db_column="superseded_bill_id", on_delete=django.db.models.deletion.PROTECT, related_name="correction_as_superseded", to="wb_core.bill", unique=True)),
                        ("corrected_bill", models.ForeignKey(db_column="corrected_bill_id", on_delete=django.db.models.deletion.PROTECT, related_name="correction_as_corrected", to="wb_core.bill")),
                    ],
                    options={
                        "managed": False,
                        "db_table": "bill_correction",
                        "indexes": [models.Index(fields=["connection", "billing_year", "billing_month"], name="ix_correction_period")],
                        "constraints": [models.CheckConstraint(check=models.Q(billing_month__gte=1, billing_month__lte=12), name="chk_correction_month")],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "ALTER TABLE penalty_rule MODIFY basis ENUM('percent_of_ytd_unpaid','percent_of_bill','fixed_amount','remaining_unpaid') NOT NULL",
                        "ALTER TABLE penalty_charge MODIFY basis_used ENUM('percent_of_ytd_unpaid','percent_of_bill','fixed_amount','legacy_unknown','remaining_unpaid') NOT NULL",
                        'ALTER TABLE bill ADD COLUMN tariff_snapshot JSON NULL',
                        'ALTER TABLE penalty_charge ADD COLUMN bill_id BIGINT UNSIGNED NULL, ADD UNIQUE KEY uq_penalty_bill (bill_id), ADD CONSTRAINT fk_penalty_bill FOREIGN KEY (bill_id) REFERENCES bill (bill_id) ON DELETE RESTRICT',
                        'CREATE TABLE bill_correction ( correction_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, consumer_id VARCHAR(15) NOT NULL, superseded_bill_id BIGINT UNSIGNED NOT NULL, corrected_bill_id BIGINT UNSIGNED NOT NULL, billing_year INT NOT NULL, billing_month TINYINT NOT NULL, old_reading INT NULL, new_reading INT NOT NULL, old_amount DOUBLE NULL, new_amount DOUBLE NULL, difference DOUBLE NOT NULL, reason VARCHAR(500) NOT NULL, performed_by VARCHAR(20) NOT NULL, performed_on DATETIME(6) NOT NULL, PRIMARY KEY (correction_id), UNIQUE KEY uq_correction_superseded (superseded_bill_id), KEY ix_correction_period (consumer_id, billing_year, billing_month), CONSTRAINT fk_correction_connection FOREIGN KEY (consumer_id) REFERENCES connection (consumer_id) ON DELETE RESTRICT, CONSTRAINT fk_correction_superseded FOREIGN KEY (superseded_bill_id) REFERENCES bill (bill_id) ON DELETE RESTRICT, CONSTRAINT fk_correction_corrected FOREIGN KEY (corrected_bill_id) REFERENCES bill (bill_id) ON DELETE RESTRICT, CONSTRAINT chk_correction_month CHECK (billing_month BETWEEN 1 AND 12) ) ENGINE=InnoDB',
                    ],
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
