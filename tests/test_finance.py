import re
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import sqlalchemy as sa
from werkzeug.datastructures import MultiDict

from app.modules.builder import create_app
from app.modules.builder import catalog
from app.modules.builder.finance import dashboard, defaults, finance_modules, install_defaults
from app.modules.builder.records import Records


class FinanceTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = {
            "TESTING": True,
            "SECRET_KEY": "test-only",
            "DATABASE_URL": f"sqlite:///{Path(directory.name) / 'finance.db'}",
        }
        self.app = create_app(self.config)
        self.engine = self.app.extensions["builder_engine"]
        self.addCleanup(self.engine.dispose)
        self.client = self.app.test_client()
        response = self.client.get("/settings")
        self.csrf = re.search(r'name="_csrf" value="([^"]+)"', response.text)[1]
        with self.engine.connect() as conn:
            self.modules = finance_modules(conn)

    def form(self, role, values):
        fields = {f.label: catalog.key(f) for f in self.modules[role].fields}
        return MultiDict([(fields[label], item) for label, value in values.items()
                          for item in (value if isinstance(value, list) else [str(value)])])

    def record(self, role, **values):
        with self.engine.begin() as conn:
            return Records(conn, self.modules[role]).write(None, self.form(role, values))

    def post_record(self, role, values, record_id=None):
        module = self.modules[role]
        url = f"/modules/{module.id}/{record_id}/edit" if record_id else f"/modules/{module.id}/new"
        form = self.form(role, values)
        form["_csrf"] = self.csrf
        return self.client.post(url, data=form)

    def transaction(self, account, when, direction, amount, **values):
        return self.record("transactions", **{
            "Date": when, "Direction": direction, "Amount": amount,
            "Category": "Other", "Tax deductible": "No", "Bank account": account, **values,
        })

    def test_defaults_restart_and_idempotent_install_preserve_customisation(self):
        self.assertEqual(len(self.modules), 8)
        with self.engine.begin() as conn:
            module = self.modules["users"]
            field = module.fields[0]
            conn.execute(catalog.fields.update().where(catalog.fields.c.id == field.id).values(list=None))
            install_defaults(conn)
            self.assertIsNone(catalog.load(conn, module.id).fields[0].list)
        user = self.record("users", Name="Tenant Example", Type="Tenant")
        restarted = create_app(self.config)
        self.addCleanup(restarted.extensions["builder_engine"].dispose)
        with restarted.extensions["builder_engine"].connect() as conn:
            self.assertEqual(conn.scalar(sa.select(sa.func.count()).select_from(defaults)), 8)
            self.assertEqual(conn.scalar(sa.select(sa.func.count()).select_from(module.table)), 1)
        for module in self.modules.values():
            for url in [f"/modules/{module.id}", f"/modules/{module.id}/new", f"/settings/{module.id}"]:
                self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get(f"/modules/{module.id}/9999").status_code, 404)
        self.assertGreater(user, 0)
        response = self.client.post("/settings", data={"_csrf": self.csrf, "action": "finance"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("Finance dashboard", self.client.get("/").text)

    def test_cash_balances_month_boundaries_transfers_and_future_transactions(self):
        a = self.record("accounts", Name="Everyday", **{"Opening date": "2026-11-01", "Opening balance": "1000.10"})
        b = self.record("accounts", Name="Savings", **{"Opening date": "2026-11-01", "Opening balance": "200"})
        self.record("accounts", Name="Future", **{"Opening date": "2026-12-01", "Opening balance": "900"})
        self.transaction(a, "2026-10-31", "Expense", "100")
        self.transaction(a, "2026-11-01", "Income", "3000")
        self.transaction(a, "2026-11-24", "Expense", "500.05", Category="Bills")
        self.transaction(a, "2026-11-24", "Transfer out", "200")
        self.transaction(b, "2026-11-24", "Transfer in", "200")
        self.transaction(a, "2026-11-25", "Expense", "999")
        with self.engine.connect() as conn:
            report = dashboard(conn, date(2026, 11, 24))
        self.assertEqual(report["income"], Decimal("3000"))
        self.assertEqual(report["expenses"], Decimal("500.05"))
        self.assertEqual(report["savings"], Decimal("2499.95"))
        self.assertEqual(report["cash"], Decimal("3700.05"))
        self.assertEqual(report["accounts"][0]["balance"], Decimal("3300.05"))
        self.assertIsNone(report["accounts"][2]["balance"])
        self.assertEqual(report["categories"], [("Bills", Decimal("500.05"))])
        with self.engine.connect() as conn:
            empty = dashboard(conn, date(2026, 10, 1))
        self.assertEqual(empty["savings"], 0)
        self.assertIsNone(empty["savings_rate"])

    def test_property_investor_and_sole_trader_linked_workflows(self):
        tenant = self.record("users", Name="Example Tenant", Type="Tenant")
        customer = self.record("users", Name="Example Customer", Type="Customer")
        account = self.record("accounts", Name="Business", **{"Opening date": "2026-07-01", "Opening balance": "0"})
        contract = self.record("contracts", Name="Consulting agreement", User=customer, Type="Service", Status="Active")
        property_id = self.record("properties", Address="Example NSW property", State="NSW", Tenants=[str(tenant)])
        invoice = self.record("invoices", Description="Consulting", Customer=customer, Contract=contract,
                              **{"Amount excluding GST": "1000", "GST amount": "100"})
        order = self.record("orders", Description="Equipment", Contract=contract,
                            **{"Amount excluding GST": "200", "GST amount": "20"})
        self.transaction(account, "2026-06-30", "Income", "10000", Property=property_id)
        self.transaction(account, "2026-07-01", "Income", "2000", Property=property_id, Category="Rent")
        self.transaction(account, "2026-11-01", "Expense", "2500", Property=property_id,
                         **{"Tax deductible": "Yes", "Category": "Interest"})
        self.transaction(account, "2026-11-01", "Expense", "400", Property=property_id, Category="Loan principal")
        self.transaction(account, "2026-11-01", "Expense", "100", Property=property_id,
                         **{"Tax deductible": "Review"})
        self.transaction(account, "2026-11-01", "Income", "1100", Invoice=invoice, Contract=contract, User=customer)
        self.transaction(account, "2026-11-01", "Expense", "220", **{"Purchase order": order})
        self.record("stocks", Name="Example ASX holding", Ticker="EXAMPLE", Exchange="ASX", Units="10.5",
                    **{"Cost per unit": "20", "Price per unit": "25", "Price date": "2026-11-24"})
        with self.engine.connect() as conn:
            report = dashboard(conn, date(2026, 11, 24))
        p = report["properties"][0]
        self.assertEqual(p["tenants"], ["Example Tenant"])
        self.assertEqual(p["cash_flow"], Decimal("-1000"))
        self.assertEqual(p["result"], Decimal("-500"))
        self.assertEqual(p["deductible"], Decimal("2500"))
        self.assertEqual(p["review"], Decimal("100"))
        self.assertEqual(p["gearing"], "Negative")
        self.assertEqual(report["income"], Decimal("1100"))  # Invoice itself is not cash.
        self.assertEqual(report["stocks"][0]["value"], Decimal("262.50"))
        self.assertEqual(report["stocks"][0]["gain"], Decimal("52.50"))
        response = self.client.get(f"/modules/{self.modules['invoices'].id}/{invoice}")
        self.assertIn("A$1,100.00", response.text)
        self.assertIn(f'href="/modules/{self.modules["contracts"].id}/{contract}"', response.text)
        self.assertIn("Example Tenant", self.client.get("/").text)
        response = self.post_record("properties", {"Tenants": [str(customer)]}, property_id)
        self.assertEqual(response.status_code, 400)
        response = self.post_record("users", {"Name": "Example Tenant", "Type": "Customer"}, tenant)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post_record("invoices", {"Customer": tenant}).status_code, 400)

    def test_finance_validation_money_and_date_errors_do_not_save(self):
        account = self.record("accounts", Name="Bank", **{"Opening date": "2026-11-01", "Opening balance": "-10"})
        base = {"Date": "2026-11-01", "Direction": "Expense", "Amount": "12.34",
                "Tax deductible": "No", "Category": "Bills", "Bank account": account}
        for amount in ["-1", "0", "NaN", "Infinity", "12.345", "1e1000", "1e1000000", "invalid"]:
            response = self.post_record("transactions", {**base, "Amount": amount})
            self.assertEqual(response.status_code, 400, amount)
        for values in [{}, {**base, "Date": "bad"}, {**base, "Bank account": 999},
                       {**base, "Direction": "bad"}]:
            self.assertEqual(self.post_record("transactions", values).status_code, 400)
        response = self.post_record("transactions", base)
        self.assertEqual(response.status_code, 302)
        self.assertIn("A$12.34", self.client.get(response.location).text)
        amount_field = next(f for f in self.modules["transactions"].fields if f.label == "Amount")
        listing = f"/modules/{self.modules['transactions'].id}"
        self.assertIn("A$12.34", self.client.get(listing, query_string={
            catalog.key(amount_field): "12.3400",
        }).text)
        self.assertEqual(self.client.get(listing, query_string={
            catalog.key(amount_field): "invalid",
        }).status_code, 400)
        record_id = int(response.location.rsplit("/", 1)[1])
        self.assertEqual(self.post_record("transactions", {**base, "Amount": "bad"}, record_id).status_code, 400)
        self.assertIn("A$12.34", self.client.get(response.location).text)
        self.assertEqual(self.post_record("contracts", {"Start date": "2026-11-02", "End date": "2026-11-01"}).status_code, 400)

    def test_exact_decimal_storage_and_incomplete_legacy_warning(self):
        self.record("accounts", Name="Exact balance", **{
            "Opening date": "2026-11-01", "Opening balance": "9999999999999999.99",
        })
        self.record("stocks", Name="Fractional units", Units="99999999999999.9999",
                    **{"Cost per unit": "0.01", "Price per unit": "0.02"})
        with self.engine.begin() as conn:
            conn.execute(self.modules["transactions"].table.insert().values())
        with self.engine.connect() as conn:
            report = dashboard(conn, date(2026, 11, 24))
        self.assertEqual(report["cash"], Decimal("9999999999999999.99"))
        self.assertEqual(report["stocks"][0]["Units"], Decimal("99999999999999.9999"))
        self.assertEqual(report["incomplete"], 1)
        self.assertIn("incomplete transaction(s) excluded", self.client.get("/").text)

    def test_install_into_existing_builder_and_incompatible_install_rollback(self):
        # Simulate an existing builder DB rather than a new auto-provisioned DB.
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        app = create_app({**self.config, "FINANCE_DEFAULTS": False,
                          "DATABASE_URL": f"sqlite:///{Path(directory.name) / 'existing.db'}"})
        engine = app.extensions["builder_engine"]
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            module_id = catalog.create_module(conn, "Transactions", "T{n}")
            catalog.add_field(conn, catalog.load(conn, module_id), {"label": "Amount", "kind": "text"})
        with self.assertRaises(catalog.Invalid):
            with engine.begin() as conn:
                install_defaults(conn)
        with engine.connect() as conn:
            self.assertEqual(conn.scalar(sa.select(sa.func.count()).select_from(catalog.modules)), 1)
            self.assertEqual(conn.scalar(sa.select(sa.func.count()).select_from(defaults)), 0)
        # Compatible existing custom modules and their records are left untouched.
        with engine.begin() as conn:
            conn.execute(catalog.modules.update().where(catalog.modules.c.id == module_id).values(name="Legacy"))
            install_defaults(conn)
        with engine.connect() as conn:
            self.assertEqual(conn.scalar(sa.select(sa.func.count()).select_from(catalog.modules)), 9)
