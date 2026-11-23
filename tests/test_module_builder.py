import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import sqlalchemy as sa

from app.modules.builder import create_app


class BuilderTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{Path(directory.name) / 'finance.db'}",
        }
        self.start_app()

    def start_app(self):
        app = create_app(self.config)
        self.client = app.test_client()
        self.engine = app.extensions["builder_engine"]
        self.addCleanup(self.engine.dispose)
        settings = self.client.get("/settings")
        self.csrf = re.search(r'name="_csrf" value="([^"]+)"', settings.text)[1]

    def post(self, url, data, status=302):
        response = self.client.post(url, data={**data, "_csrf": self.csrf})
        self.assertEqual(response.status_code, status, response.text)
        return response

    def module(self, name, pattern):
        return self.post("/settings", {"name": name, "pattern": pattern}).location

    def field(self, design, label, kind, **settings):
        self.post(design, {"action": "field", "label": label, "kind": kind, **settings})

    def record_numbers(self, url, **query):
        response = self.client.get(url, query_string=query)
        self.assertEqual(response.status_code, 200, response.text)
        return re.findall(r'<td><a href="[^"]+">([^<]+)</a></td>', response.text)

    def test_build_and_extend_schema_then_restart(self):
        design = self.module("Transactions", "TRN_{n}")
        self.field(design, "Memo", "text")
        first = self.post("/modules/1/new", {"f_1": "Original record"}).location
        self.field(design, "Paid", "date")
        self.field(design, "Status", "radio", choices="Open\nClosed")
        self.field(design, "Method", "dropdown", choices="Cash\nCard")
        self.field(design, "Flags", "multi", choices="Home\nRecurring")
        inspector = sa.inspect(self.engine)
        columns = {c["name"] for c in inspector.get_columns("builder_records_1")}
        self.assertEqual(columns, {"id", "f_1", "f_2", "f_3", "f_4"})
        self.assertTrue(inspector.has_table("builder_links_5"))
        edit = first + "/edit"
        data = {"f_1": "Original record", "f_2": "2026-03-14", "f_3": "Open",
                "f_4": "Card", "f_5": ["Home", "Recurring"]}
        self.post(edit, data)
        self.post(edit, {**data, "f_1": "Bad edit", "f_2": "not a date"}, 400)
        self.post(edit, {**data, "f_5": ["Unknown"]}, 400)
        self.start_app()
        detail = self.client.get(first).text
        for value in ("Original record", "2026-03-14", "Open", "Card", "Home, Recurring"):
            self.assertIn(value, detail)
        self.assertNotIn("Bad edit", detail)
        self.assertEqual(self.record_numbers("/modules/1", f_5="Recurring"), ["TRN_0"])
        self.assertIn('href="/modules/1"', self.client.get("/settings").text)

    def test_link_search_filter_clear_and_numeric_order(self):
        tags = self.module("Tags", "TAG_{n}")
        self.field(tags, "Name", "text")
        for tag in ["Rent", "Mortgage"]:
            self.post("/modules/1/new", {"f_1": tag})
        design = self.module("Transactions", "TRN_{n}")
        self.field(design, "Tags", "related_many", target="1")
        self.field(design, "Primary tag", "related", target="1")
        for i in range(12):
            data = {"f_2": ["1", "2"]} if i == 2 else {"f_3": "2"} if i == 10 else {}
            self.post("/modules/2/new", data)
        self.assertEqual(self.record_numbers("/modules/2"), [f"TRN_{i}" for i in range(12)])
        self.assertEqual(self.record_numbers("/modules/2", q="mOrT", sort="desc"), ["TRN_10", "TRN_2"])
        self.assertEqual(self.record_numbers("/modules/2", f_2="2"), ["TRN_2"])
        self.assertEqual(self.record_numbers("/modules/2", f_3="2"), ["TRN_10"])
        edit = "/modules/2/3/edit"
        self.assertIn('value="1" selected>Rent (TAG_0)', self.client.get(edit).text)
        self.post(edit, {"f_2": "99"}, 400)
        self.post(edit, {"f_3": ["1", "2"]}, 400)
        self.assertEqual(self.record_numbers("/modules/2", q="rent"), ["TRN_2"])
        self.post("/modules/1/1/edit", {"f_1": "Housing"})
        self.assertEqual(self.record_numbers("/modules/2", q="housing"), ["TRN_2"])
        self.post(edit, {})
        self.assertEqual(self.record_numbers("/modules/2", q="housing"), [])

    def test_independent_view_layouts_and_hidden_field_preservation(self):
        design = self.module("Test", "T{n}")
        self.field(design, "Memo", "text")
        self.field(design, "Status", "dropdown", choices="Open\nClosed")
        record = self.post("/modules/1/new", {"f_1": "needle", "f_2": "Open"}).location
        layout = {"action": "layout", "list_2": "1", "detail_1": "2", "detail_2": "1",
                  "edit_2": "1", "searchable_2": "on", "filterable_2": "on"}
        self.post(design, layout)
        builder = self.client.get(design)
        self.assertEqual(builder.status_code, 200)
        self.assertIn('name="list_1" value=""', builder.text)
        self.assertIn('name="detail_1" value="2"', builder.text)
        self.assertIn('name="filterable_2" checked', builder.text)
        self.post(design, {**layout, "list_1": "1", "detail_2": "invalid"}, 400)
        listing = self.client.get("/modules/1").text
        self.assertNotIn("<th>Memo</th>", listing)
        self.assertIn("<th>Status</th>", listing)
        self.assertEqual(self.record_numbers("/modules/1", q="needle"), [])
        self.assertEqual(self.record_numbers("/modules/1", q="open", f_2="Open"), ["T0"])
        self.assertEqual(self.record_numbers("/modules/1", q="open", f_2="Closed"), [])
        self.assertNotIn('name="f_1"', self.client.get(record + "/edit").text)
        self.post(record + "/edit", {"f_1": "overwrite", "f_2": "Closed"})
        detail = self.client.get(record).text
        self.assertLess(detail.index("<dt>Status"), detail.index("<dt>Memo"))
        self.assertIn("needle", detail)
        self.assertNotIn("overwrite", detail)

    def test_invalid_definitions_do_not_mutate_schema(self):
        self.post("/settings", {"name": "Bad", "pattern": "TRN"}, 400)
        design = self.module("People", "P{n}")
        self.field(design, "Manager", "related", target="1")
        self.post("/modules/1/new", {})
        self.post("/modules/1/new", {"f_1": "1"})
        self.assertEqual(self.record_numbers("/modules/1", f_1="1"), ["P1"])
        for data in [
            {"label": "Manager", "kind": "text"},
            {"label": "Typo", "kind": "related", "target": "999"},
            {"label": "Empty", "kind": "radio", "choices": "\n"},
        ]:
            self.post(design, {"action": "field", **data}, 400)
        self.assertEqual(self.client.get("/modules/1/100").status_code, 404)
        self.assertEqual(self.client.post(design, data={"action": "layout"}).status_code, 400)
        self.assertEqual(set(sa.inspect(self.engine).get_table_names()), {
            "builder_modules", "builder_fields", "builder_records_1", "builder_links_1",
        })
