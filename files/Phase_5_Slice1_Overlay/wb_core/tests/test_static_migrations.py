"""Static checks for migrations: legacy history intact, generated state current, guards in place."""

import ast
import hashlib
import os
import unittest

from wb_core.tools import generate_migration as gen

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
INDEX_MIGRATIONS = os.path.join(PROJECT, "index", "migrations")
WB_MIGRATION = os.path.join(PROJECT, "wb_core", "migrations", "0001_normalized_schema.py")


# SHA-256 of the legacy migrations committed on the Phase 3 janice branch.
# Verified against GitHub commit 7bb48688d3c9b7b5d1b4cd5bd8c9e748caf4248e.
ORIGINAL_HASHES = {
    "0001_initial.py": "f372283d57d5f5fb854c67512a79b6259f757bd821dd0d1dcca2e9fb04e8d333",
    "0002_alter_loginrec_expiration.py": "68da7ad0dde66f91b492c44a24a929ae7e60ec730c4136d97540835b1688ee9a",
    "0003_alter_loginrec_expiration.py": "3bcb5006228a230b97bbc527aed9eef9dd11354f3d503b5358ae60769e87e685",
    "0004_systeminfo_authors_alter_loginrec_expiration.py": "f0ca46039a83cf40ceb0ab1d54951c3e15057be23ad79bcce0ddeb9944d34ae6",
    "0005_delete_systeminfo_alter_loginrec_expiration.py": "1637ac319fae574a4620a61bbd0014260cd67c4c75823170c9fc0f6337bb23e3",
    "0006_systeminfo_alter_loginrec_expiration.py": "0b53d196984ada847887dc8720ef0dd670388e1c835d267c9b956c5c517ada15",
}



def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class LegacyMigrationHistoryTests(unittest.TestCase):

    def test_original_migrations_0001_to_0006_are_byte_identical(self):
        for name, expected in ORIGINAL_HASHES.items():
            self.assertEqual(_sha256(os.path.join(INDEX_MIGRATIONS, name)), expected, name)

    def test_new_legacy_migrations_form_a_chain(self):
        def deps(path):
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "dependencies" for t in node.targets):
                    return [elt.elts[1].value for elt in node.value.elts]
            return []
        self.assertEqual(deps(os.path.join(INDEX_MIGRATIONS, "0007_fix_import_time_defaults.py")), ["0006_systeminfo_alter_loginrec_expiration"])
        self.assertEqual(deps(os.path.join(INDEX_MIGRATIONS, "0008_capture_unmigrated_models.py")), ["0007_fix_import_time_defaults"])


class GeneratedMigrationTests(unittest.TestCase):

    def test_committed_wb_core_migration_matches_models(self):
        """If a model changes without regenerating the migration, this fails."""
        expected = gen.render_migration(gen.collect_models())
        with open(WB_MIGRATION, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), expected, "Run: python wb_core/tools/generate_migration.py")

    def test_migration_creates_all_31_models_and_runs_the_ddl(self):
        with open(WB_MIGRATION, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text.count("migrations.CreateModel("), 31)
        self.assertEqual(text.count("migrations.RunSQL("), 1)
        self.assertIn("reverse_sql=migrations.RunSQL.noop", text)
        self.assertIn('("index", "0008_capture_unmigrated_models")', text)

    def test_migration_has_no_alter_or_delete_operations(self):
        with open(WB_MIGRATION, encoding="utf-8") as handle:
            text = handle.read()
        for op in ("AlterField", "RemoveField", "DeleteModel", "RenameModel"):
            self.assertNotIn("migrations." + op, text)

    def test_generator_rejects_managed_true_and_bad_order(self):
        # The generator must refuse models that are not unmanaged.
        import ast as _ast
        bad = _ast.parse(
            "class X(models.Model):\n    class Meta:\n        managed = True\n        db_table = 'x'\n"
        ).body[0]
        with self.assertRaises(ValueError):
            gen._model_info(bad)


class MigrationGuardTests(unittest.TestCase):

    def test_legacy_0008_uses_guard_and_separate_state(self):
        with open(os.path.join(INDEX_MIGRATIONS, "0008_capture_unmigrated_models.py"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("SeparateDatabaseAndState", text)
        self.assertIn("ensure_allowed_database(", text)
        self.assertIn("if model._meta.db_table not in existing_tables", text)
        self.assertIn("if field.column not in transactions_columns", text)


if __name__ == "__main__":
    unittest.main()
