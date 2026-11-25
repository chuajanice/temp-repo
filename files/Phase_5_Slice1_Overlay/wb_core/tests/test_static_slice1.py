"""Phase 5 Slice 1 static tests. No Django, no database. They check the pure rules and the structure of the
Slice 1 code: the switch, the guarded branches, normalized-only business code, atomic writes and the form and
template contract with the existing frontend."""

import ast
import os
import unittest

from wb_core.services.consumer_rules import DEFAULT_PENALTY_CODE, next_consumer_id

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # project root: .../wb_core/tests -> .../wb_core -> project


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def _orm_calls(tree):
    """Yield (call, has_using) for each call whose receiver chain contains an '.objects' attribute."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr == "using":          # the .using(...) call itself is the scoping, not a query
            continue
        cur = node.func.value
        has_using = False
        found = False
        while True:
            if isinstance(cur, ast.Attribute) and cur.attr == "objects":
                found = True
                break
            if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                if cur.func.attr == "using":
                    has_using = True
                cur = cur.func.value
            elif isinstance(cur, ast.Attribute):
                cur = cur.value
            else:
                break
        if found:
            yield node, has_using


class PureRuleTests(unittest.TestCase):

    def test_next_id_after_an_existing_connection(self):
        self.assertEqual(next_consumer_id("0000000306-01"), "0000000307-01")

    def test_first_id_when_no_connections(self):
        self.assertEqual(next_consumer_id(None), "0000000001-01")

    def test_id_crosses_the_nine_boundary_with_padding(self):
        self.assertEqual(next_consumer_id("0000009999-01"), "0000010000-01")

    def test_ids_are_ten_digits_with_the_suffix(self):
        for last in ("0000000000-01", "0000000042-01", "0009999999-01"):
            new = next_consumer_id(last)
            self.assertEqual(len(new.split("-")[0]), 10)
            self.assertTrue(new.endswith("-01"))

    def test_default_penalty_is_the_legacy_default(self):
        self.assertEqual(DEFAULT_PENALTY_CODE, "P001")


class SwitchTests(unittest.TestCase):

    def test_setting_defaults_to_legacy_and_is_validated(self):
        src = _read("wb2/settings.py")
        self.assertIn("WB_BUSINESS_DB = _env('WB_BUSINESS_DB', 'legacy')", src)
        self.assertIn("if WB_BUSINESS_DB not in ('legacy', 'normalized'):", src)

    def test_four_guarded_branches_exist_in_views(self):
        src = _read("index/views.py")
        self.assertEqual(src.count("if use_normalized():"), 4)
        for name in ("consumer_list_normalized", "consumer_form_normalized", "consumer_update_normalized"):
            self.assertIn(name, src)

    def test_business_helpers_do_not_import_legacy_models(self):
        for rel in ("index/business_views.py", "index/business_forms.py", "index/business_db.py",
                    "wb_core/services/consumers.py"):
            tree = ast.parse(_read(rel))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    legacy = node.module == "index.models" or (node.level and node.module == "models")
                    self.assertFalse(legacy, rel)
                if isinstance(node, ast.Name):
                    self.assertNotEqual(node.id, "ConsumerInfo", rel)

    def test_every_orm_call_names_the_normalized_alias(self):
        for rel in ("wb_core/services/consumers.py", "index/business_views.py", "index/business_forms.py"):
            tree = ast.parse(_read(rel))
            for call, has_using in _orm_calls(tree):
                self.assertTrue(has_using, "%s line %s: ORM call without .using()" % (rel, call.lineno))

    def test_write_operations_are_atomic_on_the_normalized_alias(self):
        self.assertEqual(_read("wb_core/services/consumers.py").count("transaction.atomic(using=NORMALIZED)"), 2)

    def test_id_generation_locks_the_last_row(self):
        self.assertIn("select_for_update()", _read("wb_core/services/consumers.py"))


class FrontendContractTests(unittest.TestCase):

    @staticmethod
    def _class_fields(src, name):
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                return {t.id for item in node.body if isinstance(item, ast.Assign)
                        for t in item.targets if isinstance(t, ast.Name)}
        raise AssertionError("class %s not found" % name)

    def test_business_form_declares_exactly_the_legacy_form_fields(self):
        legacy = self._class_fields(_read("index/forms.py"), "ConsumerForm")
        new = self._class_fields(_read("index/business_forms.py"), "NormalizedConsumerForm")
        self.assertEqual(new, legacy)

    def test_templates_used_by_slice1_exist(self):
        for rel in ("templates/conlist.html", "templates/consumercreation.html"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)

    def test_business_views_render_the_same_templates_as_legacy(self):
        src = _read("index/business_views.py")
        self.assertIn('render(request, "conlist.html"', src)
        self.assertIn('render(request, "consumercreation.html"', src)


if __name__ == "__main__":
    unittest.main()
