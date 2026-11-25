"""Static checks: unmanaged models vs the reviewed DDL. Runs WITHOUT Django or a database.

The models are read with ``ast``; the DDL is parsed by wb_core.schema.ddl. Every mismatch in
table names, columns, nullability, decimal precision, ENUM values, foreign-key delete rules,
indexes or CHECK names is reported.
"""

import ast
import os
import unittest

from wb_core.schema.ddl import load_schema_file

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
MODELS_DIR = os.path.join(PKG, "models")
DDL_PATH = os.path.join(PKG, "sql", "normalized_schema_v5.sql")  # Phase 5 Slice 2 (v4 + additive billing changes)

# Columns the database maintains. They are deliberately not declared on the models.
GENERATED_COLUMNS = {
    ("bill", "active_bill_key"),
    ("meter_reading", "active_reading_key"),
    ("fee_charge", "active_fee_key"),
}
# Unique keys that depend on generated columns. Enforced by MySQL only.
DB_ONLY_UNIQUE_KEYS = {
    ("bill", "uq_bill_active"),
    ("meter_reading", "uq_reading_active"),
    ("fee_charge", "uq_fee_charge_active"),
}

FIELD_FAMILY = {
    "BigAutoField": "BIGINT", "AutoField": "INT", "BigIntegerField": "BIGINT", "IntegerField": "INT",
    "PositiveSmallIntegerField": "TINYINT", "BooleanField": "TINYINT", "CharField": "VARCHAR",
    "TextField": "TEXT", "DateField": "DATE", "DateTimeField": "DATETIME", "TimeField": "TIME",
    "DecimalField": "DECIMAL", "FloatField": "DOUBLE", "JSONField": "JSON", "ForeignKey": None,
}
ON_DELETE = {"PROTECT": "RESTRICT", "SET_NULL": "SET NULL", "CASCADE": "CASCADE"}


def _const(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "models":
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ast.unparse(node)


def load_models():
    """Return {class_name: info} for every unmanaged model in models/*.py."""
    result = {}
    for filename in sorted(os.listdir(MODELS_DIR)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        with open(os.path.join(MODELS_DIR, filename), encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=filename)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Attribute) and b.attr == "Model" for b in node.bases):
                continue
            meta = next(i for i in node.body if isinstance(i, ast.ClassDef) and i.name == "Meta")
            meta_values = {}
            for item in meta.body:
                if isinstance(item, ast.Assign):
                    meta_values[item.targets[0].id] = item.value
            fields = {}
            for item in node.body:
                if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name) and isinstance(item.value, ast.Call):
                    call = item.value
                    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "models":
                        kwargs = {kw.arg: _const(kw.value) for kw in call.keywords}
                        args = [_const(a) for a in call.args]
                        fields[item.targets[0].id] = {"type": call.func.attr, "kwargs": kwargs, "args": args, "node": call}
            result[node.name] = {"fields": fields, "meta": meta_values, "file": filename}
    return result


def _db_table(info):
    return _const(info["meta"]["db_table"])


def _column_name(name, field):
    return field["kwargs"].get("db_column", name)


class ModelToDDLTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tables = load_schema_file(DDL_PATH)
        cls.models = load_models()
        cls.by_table = {_db_table(info): (name, info) for name, info in cls.models.items()}

    def test_every_model_maps_to_a_table(self):
        self.assertEqual(len(self.models), 32)
        self.assertEqual(set(self.by_table), set(self.tables))

    def test_every_model_is_unmanaged(self):
        for name, info in self.models.items():
            self.assertIs(_const(info["meta"]["managed"]), False, name)

    def test_db_columns_match_ddl_columns_exactly(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            model_columns = {_column_name(n, f) for n, f in info["fields"].items()}
            ddl_columns = {c for c in table.columns if (table_name, c) not in GENERATED_COLUMNS}
            self.assertEqual(model_columns, ddl_columns, table_name)

    def test_generated_columns_are_not_declared_on_models(self):
        for table_name, column in GENERATED_COLUMNS:
            _, info = self.by_table[table_name]
            self.assertNotIn(column, {_column_name(n, f) for n, f in info["fields"].items()})

    def test_nullability_matches(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            for name, field in info["fields"].items():
                col = table.columns[_column_name(name, field)]
                if col.generated:
                    continue
                expect_null = bool(field["kwargs"].get("null", False))
                if field["kwargs"].get("primary_key"):
                    expect_null = False
                self.assertEqual(expect_null, col.nullable, "%s.%s" % (table_name, name))

    def test_decimal_precision_matches_ddl(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            for name, field in info["fields"].items():
                if field["type"] != "DecimalField":
                    continue
                col = table.columns[_column_name(name, field)]
                self.assertEqual(col.base_type, "DECIMAL", "%s.%s" % (table_name, name))
                self.assertEqual((field["kwargs"]["max_digits"], field["kwargs"]["decimal_places"]),
                                 (col.length, col.scale), "%s.%s" % (table_name, name))

    def test_money_fields_are_float_and_tariff_fields_stay_decimal(self):
        """Phase 4A (approved OPTION A). Money: FloatField/DOUBLE. Tariffs, rates, percentages: DECIMAL."""
        from wb_core.monetary import MONEY_COLUMNS, DECIMAL_NON_MONEY_COLUMNS
        for table, column in MONEY_COLUMNS:
            _, info = self.by_table[table]
            self.assertEqual(info["fields"][column]["type"], "FloatField", "%s.%s" % (table, column))
            self.assertEqual(self.tables[table].columns[column].base_type, "DOUBLE", "%s.%s" % (table, column))
        for table, column in DECIMAL_NON_MONEY_COLUMNS:
            _, info = self.by_table[table]
            self.assertEqual(info["fields"][column]["type"], "DecimalField", "%s.%s" % (table, column))
            self.assertEqual(self.tables[table].columns[column].base_type, "DECIMAL", "%s.%s" % (table, column))

    def test_type_families_match(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            for name, field in info["fields"].items():
                if field["type"] == "ForeignKey":
                    continue
                col = table.columns[_column_name(name, field)]
                # A CharField with choices is the model form of a MySQL ENUM column.
                if field["type"] == "CharField" and "choices" in field["kwargs"] or any(
                        kw.arg == "choices" for kw in field["node"].keywords):
                    expected_family = "ENUM"
                else:
                    expected_family = FIELD_FAMILY[field["type"]]
                self.assertEqual(col.base_type, expected_family, "%s.%s" % (table_name, name))

    def test_enum_choices_match_ddl(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            for name, field in info["fields"].items():
                if "choices" not in field["kwargs"] and not any(
                        kw.arg == "choices" for kw in field["node"].keywords):
                    continue
                choices_node = next(kw.value for kw in field["node"].keywords if kw.arg == "choices")
                values = tuple(_const(elt.elts[0]) for elt in choices_node.elts)
                col = table.columns[_column_name(name, field)]
                self.assertEqual(col.base_type, "ENUM", "%s.%s" % (table_name, name))
                self.assertEqual(values, col.enum_values, "%s.%s" % (table_name, name))

    def test_defaults_for_status_and_flags(self):
        # A default in the model must agree with the DDL default (where the DDL states one).
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            for name, field in info["fields"].items():
                if "default" not in field["kwargs"]:
                    continue
                col = table.columns[_column_name(name, field)]
                if col.default is None or callable(field["kwargs"]["default"]):
                    continue
                default = field["kwargs"]["default"]
                if isinstance(default, bool):
                    default = 1 if default else 0
                if isinstance(default, (int, float)):
                    self.assertAlmostEqual(float(default), float(col.default.strip("'")), places=6, msg="%s.%s" % (table_name, name))
                else:
                    self.assertEqual(str(default), col.default.strip("'"), "%s.%s" % (table_name, name))

    def test_foreign_key_targets_and_delete_rules_match(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            ddl_fks = {fk.name: fk for fk in table.foreign_keys}
            model_fks = []
            for name, field in info["fields"].items():
                if field["type"] != "ForeignKey":
                    continue
                target = self.models[field["args"][0]]
                model_fks.append((_column_name(name, field), _db_table(target), field["kwargs"]["on_delete"]))
            # Foreign keys to the legacy user table are plain text columns on the models (tested separately).
            ddl_list = [(fk.columns[0], fk.ref_table, fk.on_delete) for fk in table.foreign_keys if fk.ref_table != "index_systemusers"]
            model_list = [(c, r, "RESTRICT" if d == "PROTECT" else ("SET NULL" if d == "SET_NULL" else d)) for c, r, d in model_fks]
            self.assertEqual(sorted(model_list), sorted(ddl_list), table_name)

    def test_foreign_keys_to_user_table_are_plain_columns(self):
        # index_systemusers lives in the legacy database. Models store the username as text.
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            for fk in table.foreign_keys:
                if fk.ref_table == "index_systemusers":
                    name = next(n for n, f in info["fields"].items() if _column_name(n, f) == fk.columns[0])
                    self.assertEqual(info["fields"][name]["type"], "CharField", "%s.%s" % (table_name, name))

    def test_indexes_match_ddl_keys(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            model_indexes = {}
            indexes_node = info["meta"].get("indexes")
            if indexes_node is not None:
                for call in indexes_node.elts:
                    name = _const(next(kw.value for kw in call.keywords if kw.arg == "name"))
                    fields_node = next(kw.value for kw in call.keywords if kw.arg == "fields")
                    fields = tuple(_const(e) for e in fields_node.elts)
                    model_indexes[name] = fields
            ddl_fk_names = {fk.name for fk in table.foreign_keys}
            ddl_keys = {k: v for k, v in table.keys.items() if k not in ddl_fk_names}
            mapped = {}
            for key, cols in ddl_keys.items():
                mapped[key] = tuple(self._model_field_for_column(info, c) for c in cols)
            self.assertEqual(model_indexes, mapped, table_name)

    def _model_field_for_column(self, info, column):
        for name, field in info["fields"].items():
            if _column_name(name, field) == column:
                return name
        raise AssertionError("no model field for column %s" % column)

    def test_unique_together_matches_ddl(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            node = info["meta"].get("unique_together")
            model_unique = set()
            if node is not None:
                for tup in node.elts:
                    model_unique.add(tuple(_const(e) for e in tup.elts))
            ddl_unique = set()
            for key, cols in table.unique_keys.items():
                if (table_name, key) in DB_ONLY_UNIQUE_KEYS:
                    continue
                if len(cols) > 1:
                    ddl_unique.add(tuple(self._model_field_for_column(info, c) for c in cols))
            self.assertEqual(model_unique, ddl_unique, table_name)

    def test_check_constraint_names_match_ddl(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            node = info["meta"].get("constraints")
            model_checks = set()
            if node is not None:
                for call in node.elts:
                    name = _const(next(kw.value for kw in call.keywords if kw.arg == "name"))
                    model_checks.add(name)
            self.assertEqual(model_checks, set(table.checks), table_name)

    def test_index_and_constraint_names_fit_django_limit(self):
        for table_name, table in self.tables.items():
            for name in list(table.keys) + list(table.unique_keys) + list(table.checks) + [f.name for f in table.foreign_keys]:
                self.assertLessEqual(len(name), 30, "%s.%s" % (table_name, name))

    def test_primary_keys_match(self):
        for table_name, table in self.tables.items():
            _, info = self.by_table[table_name]
            pk_fields = [n for n, f in info["fields"].items() if f["kwargs"].get("primary_key")]
            self.assertEqual(
                tuple(_column_name(n, info["fields"][n]) for n in pk_fields),
                tuple(table.primary_key), table_name)

    def test_surrogate_key_on_barangay_monthly_summary(self):
        # Correction A-5: the summary table has a single-column key and a UNIQUE period key.
        _, info = self.by_table["barangay_monthly_summary"]
        self.assertEqual(info["fields"]["summary_id"]["type"], "BigAutoField")
        self.assertTrue(info["fields"]["summary_id"]["kwargs"].get("primary_key"))
        natural_keys = [tuple(_const(e) for e in t.elts) for t in info["meta"]["unique_together"].elts]
        self.assertIn(("barangay", "billing_year", "billing_month"), natural_keys)


if __name__ == "__main__":
    unittest.main()
