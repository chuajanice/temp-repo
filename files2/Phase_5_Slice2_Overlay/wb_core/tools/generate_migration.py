"""Generate ``wb_core/migrations/0001_normalized_schema.py`` from the model source files.

Why this exists
---------------
The normalized models are unmanaged, so Django's autodetector cannot produce the migration
state reliably for them (and it would emit DDL for the generated columns if they were declared).
This tool reads the model classes with ``ast`` (no Django import needed), writes one
``CreateModel`` per model in dependency order, and appends a ``RunSQL`` that creates the tables
from the reviewed DDL file.

The output is deterministic. ``wb_core/tests/test_static_migrations.py`` regenerates the file
and fails if the committed copy differs, so model edits cannot silently drift from the migration.

Usage (from the project root):
    python wb_core/tools/generate_migration.py            # rewrite the migration
    python wb_core/tools/generate_migration.py --check    # exit 1 if the file is stale
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
MODELS_DIR = os.path.join(PKG, "models")
MIGRATION_PATH = os.path.join(PKG, "migrations", "0001_normalized_schema.py")
V3_DDL = os.path.join(PKG, "sql", "normalized_schema_v3.sql")

# Migration 0001 is applied history. It must keep the v3 DECIMAL state of the money fields, even though the
# models now use FloatField (Phase 4A, migration 0002 changes them). Precision is read from the v3 DDL.
_sys_path_ready = False


def _baseline_money_precision():
    import sys
    global _sys_path_ready
    if not _sys_path_ready:
        sys.path.insert(0, os.path.dirname(PKG))
        _sys_path_ready = True
    from wb_core.monetary import MONEY_COLUMNS
    from wb_core.schema.ddl import load_schema_file
    tables = load_schema_file(V3_DDL)
    return {(t, c): (tables[t].columns[c].length, tables[t].columns[c].scale) for t, c in MONEY_COLUMNS}

HEADER = '''"""Create the normalized Water Billing V4 tables (wb_core).

GENERATED FILE. Do not edit by hand. Regenerate with:
    python wb_core/tools/generate_migration.py

State: one CreateModel per unmanaged model (no SQL is generated for them).
Database: RunSQL runs the reviewed DDL in wb_core/sql/normalized_schema_v3.sql.
Only the CREATE TABLE statements run; CREATE DATABASE / USE are stripped, because this
migration runs inside the target database that Django connected to.
"""

from pathlib import Path

from django.db import migrations, models

from wb_core.schema.ddl import load_normalized_statements

NORMALIZED_SQL = Path(__file__).resolve().parent.parent / "sql" / "normalized_schema_v3.sql"


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("index", "0008_capture_unmigrated_models"),
    ]

    operations = [
'''

FOOTER = '''        migrations.RunSQL(
            sql=load_normalized_statements(str(NORMALIZED_SQL)),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
'''


def _read_module(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _is_models_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "models"
    )


def _is_model_class(node):
    for base in node.bases:
        if isinstance(base, ast.Attribute) and base.attr == "Model":
            return True
    return False


def _meta(node):
    for item in node.body:
        if isinstance(item, ast.ClassDef) and item.name == "Meta":
            return item
    raise ValueError("Model %s has no Meta class" % node.name)


def _meta_value(meta, key):
    for item in meta.body:
        if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name) and item.targets[0].id == key:
            return item.value
    return None


def collect_models():
    """Return (ordered list of model info dicts) read from every models/*.py file."""
    order = []
    for node in _read_module(os.path.join(MODELS_DIR, "__init__.py")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "ALL_MODELS":
            order = [elt.id for elt in node.value.elts]
    found = {}
    for filename in sorted(os.listdir(MODELS_DIR)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        for node in _read_module(os.path.join(MODELS_DIR, filename)).body:
            if isinstance(node, ast.ClassDef) and _is_model_class(node):
                found[node.name] = (filename, node)
    if sorted(order) != sorted(found):
        raise ValueError("ALL_MODELS does not match model classes: %s" % sorted(set(order) ^ set(found)))
    models_info = []
    for name in order:
        _, node = found[name]
        models_info.append(_model_info(node))
    _check_managed_and_order(models_info)
    return models_info


def _model_info(node):
    meta = _meta(node)
    managed = _meta_value(meta, "managed")
    if not (isinstance(managed, ast.Constant) and managed.value is False):
        raise ValueError("%s must declare managed = False" % node.name)
    db_table = _meta_value(meta, "db_table")
    fields = []
    for item in node.body:
        if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name) and _is_models_call(item.value):
            fields.append((item.targets[0].id, item.value))
    refs = []
    for field_name, call in fields:
        if call.func.attr == "ForeignKey":
            target = call.args[0]
            if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
                raise ValueError("%s.%s: ForeignKey target must be a string literal" % (node.name, field_name))
            refs.append(target.value)
    return {
        "name": node.name,
        "db_table": db_table.value,
        "fields": fields,
        "refs": refs,
        "meta": meta,
    }


def _check_managed_and_order(models_info):
    seen = set()
    for info in models_info:
        for ref in info["refs"]:
            if ref not in seen:
                raise ValueError("Model %s references %s before it is created" % (info["name"], ref))
        seen.add(info["name"])


def _render_field(field_name, call, db_table=None, money=None):
    attr = call.func.attr
    parts = []
    if money is not None and db_table is not None and (db_table, field_name) in money:
        # Baseline (migration 0001): the historical DECIMAL(p,2) state, not the current FloatField.
        precision, scale = money[(db_table, field_name)]
        parts.append("max_digits=%d" % precision)
        parts.append("decimal_places=%d" % scale)
        attr = "DecimalField"
    for index, arg in enumerate(call.args):
        if attr == "ForeignKey" and index == 0:
            parts.append("to=%r" % ("wb_core." + arg.value.lower()))
        else:
            parts.append(ast.unparse(arg))
    for kw in call.keywords:
        parts.append("%s=%s" % (kw.arg, ast.unparse(kw.value)))
    return "                (%r, models.%s(%s))," % (field_name, attr, ", ".join(parts))


def _render_options(info):
    options = ["'managed': False", "'db_table': %r" % info["db_table"]]
    meta = info["meta"]
    unique_together = _meta_value(meta, "unique_together")
    if unique_together is not None:
        options.append("'unique_together': %s" % ast.unparse(unique_together))
    indexes = _meta_value(meta, "indexes")
    if indexes is not None:
        options.append("'indexes': [%s]" % ", ".join(ast.unparse(e) for e in indexes.elts))
    constraints = _meta_value(meta, "constraints")
    if constraints is not None:
        options.append("'constraints': [%s]" % ", ".join(ast.unparse(e) for e in constraints.elts))
    return "{" + ", ".join(options) + "}"


_MONEY_BASELINE = None


# Phase 5 Slice 2 additions live in migration 0003, not in 0001. Keep 0001 exactly as it was applied.
LATER_MODELS = frozenset({"BillCorrection"})
LATER_FIELDS = frozenset({("Bill", "tariff_snapshot"), ("PenaltyCharge", "bill")})
LATER_CHOICES = {
    ("PenaltyRule", "basis"): ", ('remaining_unpaid', 'remaining_unpaid')",
    ("PenaltyCharge", "basis_used"): ", ('remaining_unpaid', 'remaining_unpaid')",
}


def render_migration(models_info):
    global _MONEY_BASELINE
    if _MONEY_BASELINE is None:
        _MONEY_BASELINE = _baseline_money_precision()
    out = [HEADER]
    for info in models_info:
        if info["name"] in LATER_MODELS:
            continue
        out.append("        migrations.CreateModel(\n")
        out.append("            name=%r,\n" % info["name"])
        out.append("            fields=[\n")
        for field_name, call in info["fields"]:
            if (info["name"], field_name) in LATER_FIELDS:
                continue
            text = _render_field(field_name, call, info["db_table"], _MONEY_BASELINE)
            if (info["name"], field_name) in LATER_CHOICES:
                text = text.replace(LATER_CHOICES[(info["name"], field_name)], "")
            out.append(text + "\n")
        out.append("            ],\n")
        out.append("            options=%s,\n" % _render_options(info))
        out.append("        ),\n")
    out.append(FOOTER)
    return "".join(out)


def main(argv):
    text = render_migration(collect_models())
    if "--check" in argv:
        try:
            with open(MIGRATION_PATH, encoding="utf-8") as handle:
                current = handle.read()
        except FileNotFoundError:
            current = ""
        if current != text:
            print("STALE: %s differs from the models. Regenerate it." % MIGRATION_PATH)
            return 1
        print("OK: migration is up to date")
        return 0
    with open(MIGRATION_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    print("wrote %s (%d models)" % (MIGRATION_PATH, len(collect_models())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
