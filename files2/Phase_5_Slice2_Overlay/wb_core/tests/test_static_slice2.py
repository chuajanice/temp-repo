"""Phase 5 Slice 2 static tests: pure billing rules, code structure and safety rules. No Django, no database."""

import ast
import os
import re
import unittest

from wb_core.services import billing_rules as R

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("function %s not found" % name)


class PenaltyRuleTests(unittest.TestCase):

    def p(self, y, m):
        return R.period_index(y, m)

    def test_penalty_base_is_the_remaining_unpaid_amount(self):
        self.assertEqual(R.penalty_amount(2, 80.0), 1.6)

    def test_zero_and_overpaid_bases_never_produce_a_penalty(self):
        self.assertEqual(R.penalty_amount(2, 0.0), 0.0)
        self.assertEqual(R.penalty_amount(2, -50.0), 0.0)
        self.assertEqual(R.penalty_amount(2, 0.001), 0.0)   # below the half-centavo threshold

    def test_zero_or_missing_rate_gives_no_penalty(self):
        self.assertEqual(R.penalty_amount(0, 80.0), 0.0)
        self.assertEqual(R.penalty_amount(None, 80.0), 0.0)

    def test_run_counts_consecutive_unpaid_overdue_periods(self):
        billed = {self.p(2026, 1): 80.0, self.p(2026, 2): 50.0, self.p(2026, 3): 0.0}
        self.assertEqual(R.overdue_run(billed), [self.p(2026, 2), self.p(2026, 1)])

    def test_a_paid_most_recent_overdue_period_resets_the_counter(self):
        billed = {self.p(2026, 1): 80.0, self.p(2026, 2): 0.0, self.p(2026, 3): 50.0}
        self.assertEqual(R.overdue_run(billed), [])

    def test_a_missing_period_breaks_the_run(self):
        billed = {self.p(2026, 1): 80.0, self.p(2026, 3): 50.0, self.p(2026, 4): 10.0}
        self.assertEqual(R.overdue_run(billed), [self.p(2026, 3)])

    def test_only_the_latest_bill_means_no_overdue_periods(self):
        self.assertEqual(R.overdue_run({self.p(2026, 5): 999.0}), [])

    def test_penalty_due_uses_the_threshold(self):
        self.assertFalse(R.penalty_due(2, 3))
        self.assertTrue(R.penalty_due(3, 3))
        self.assertFalse(R.penalty_due(5, None))

    def test_tariff_regime_boundaries_match_the_legacy_formula(self):
        self.assertEqual(R.tariff_regime(2024, 9), "linear_consumer_type")
        self.assertEqual(R.tariff_regime(2024, 10), "progressive_x0.60")
        self.assertEqual(R.tariff_regime(2025, 12), "progressive_x0.60")
        self.assertEqual(R.tariff_regime(2026, 1), "progressive_x0.70")

    def test_correction_difference(self):
        self.assertEqual(R.correction_difference(100.0, 120.5), 20.5)
        self.assertEqual(R.correction_difference(None, 50.0), 50.0)


class BillingServiceStructureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = _read("wb_core/services/billing.py")
        cls.tree = ast.parse(cls.src)

    def test_no_legacy_models_and_no_broad_exception_handlers(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "index.models")
            if isinstance(node, ast.ExceptHandler):
                self.assertIsNotNone(node.type, "bare except")
                self.assertNotEqual(getattr(node.type, "id", ""), "Exception", "broad except swallows errors")

    def test_every_write_block_is_atomic_on_the_normalized_alias(self):
        self.assertGreaterEqual(self.src.count("transaction.atomic(using=NORMALIZED)"), 2)

    def test_correction_checks_authority_and_reason_before_any_write(self):
        fn = _function(self.tree, "correct_reading")
        body = ast.unparse(fn)
        self.assertLess(body.index("if not is_admin"), body.index("transaction.atomic"))
        self.assertLess(body.index("if not reason"), body.index("transaction.atomic"))

    def test_corrections_never_assess_penalties(self):
        fn = ast.unparse(_function(self.tree, "correct_reading"))
        self.assertNotIn("assess_penalties(", fn)

    def test_reading_trigger_is_the_only_caller_of_penalty_assessment(self):
        callers = [n.name for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)
                   if "assess_penalties(" in ast.unparse(n) and n.name != "assess_penalties"]
        self.assertEqual(callers, ["record_reading"])

    def test_counter_is_never_incremented_by_a_save(self):
        self.assertNotIn("penalty_counter +=", self.src)
        self.assertNotIn("penalty_counter = penalty_counter", self.src)

    def test_reading_refuses_an_existing_period_before_creating_anything(self):
        fn = ast.unparse(_function(self.tree, "record_reading"))
        self.assertLess(fn.index("ReadingAlreadyRecorded("), fn.index("MeterReading.objects.using(NORMALIZED).create"))

    def test_bill_snapshot_is_written_at_issue(self):
        fn = ast.unparse(_function(self.tree, "record_reading"))
        self.assertIn("tariff_snapshot=_snapshot(", fn)


class MigrationAndSchemaTests(unittest.TestCase):

    def test_migration_0003_creates_the_correction_table_exactly_as_v5_defines_it(self):
        v5 = _read("wb_core/sql/normalized_schema_v5.sql")
        create = re.search(r"CREATE TABLE bill_correction \((.*?)\) ENGINE=InnoDB;", v5, re.S).group(1)
        migration = _read("wb_core/migrations/0003_slice2_billing.py")
        self.assertIn(" ".join(create.split()), " ".join(migration.split()))

    def test_migration_0003_only_adds_or_extends(self):
        migration = _read("wb_core/migrations/0003_slice2_billing.py")
        # "ON DELETE RESTRICT" is a protective foreign-key clause, not a delete. Check real destructive statements.
        for forbidden in ("DROP ", "RENAME ", "TRUNCATE ", "DELETE FROM", "CHANGE COLUMN", "DECIMAL"):
            self.assertNotIn(forbidden, migration, forbidden)
        self.assertIn('("wb_core", "0002_money_double")', migration)

    def test_v5_money_columns_are_double(self):
        v5 = _read("wb_core/sql/normalized_schema_v5.sql")
        for col in ("old_amount", "new_amount", "difference"):
            self.assertRegex(v5, r"\b%s\s+DOUBLE" % col)

    def test_penalty_per_bill_is_unique_in_v5(self):
        self.assertIn("UNIQUE KEY uq_penalty_bill (bill_id)", _read("wb_core/sql/normalized_schema_v5.sql"))


class SafetyGuardTests(unittest.TestCase):

    def test_unmigrated_legacy_routes_are_guarded(self):
        src = _read("index/views.py")
        for label in ("delete a reading", "stop a meter", "enable a meter", "exempt an account", "add an issue",
                      "disconnect a consumer", "reconnect a consumer", "delete a consumer", "undo a consumer deletion"):
            self.assertIn('not_yet_in_normalized(request, "%s")' % label, src, label)

    def test_reading_screen_branch_is_present(self):
        self.assertIn("reading_screen_normalized(request, id, year)", _read("index/views.py"))

    def test_correction_command_is_plan_by_default_and_checks_the_administrator(self):
        cmd = _read("wb_core/management/commands/wb_correct_reading.py")
        self.assertIn("if not o[\"execute\"]:", cmd)
        self.assertIn("is_admin = 1", cmd)
        self.assertLess(cmd.index("if not admin:"), cmd.index("correct_reading("))


class DecimalPolicyTests(unittest.TestCase):

    def test_billing_modules_use_no_decimal_for_money(self):
        for rel in ("wb_core/services/billing.py", "wb_core/services/billing_rules.py",
                    "index/business_readings.py", "wb_core/management/commands/wb_correct_reading.py"):
            self.assertNotIn("Decimal", _read(rel), rel)


if __name__ == "__main__":
    unittest.main()
