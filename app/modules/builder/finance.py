"""Default finance metadata and cash-basis reporting; no tax assessment."""

from datetime import datetime, date
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from . import catalog
from .catalog import Invalid, key, links, load, metadata
from .records import Records


defaults = sa.Table(
    "finance_defaults", metadata,
    sa.Column("role", sa.String(40), primary_key=True),
    sa.Column("module_id", sa.ForeignKey(catalog.modules.c.id), nullable=False, unique=True),
)

# Relationship targets are role names, resolved after all modules are created.
DEFINITIONS = {
    "users": ("Users", "USR", [
        ("Name", "text"), ("Type", "dropdown", ["Customer", "Tenant"]),
        ("Email", "text"), ("Phone", "text"), ("ABN", "text"), ("Notes", "text"),
    ]),
    "accounts": ("Bank accounts", "BNK", [
        ("Name", "text"), ("Institution", "text"), ("BSB", "text"),
        ("Account reference", "text"), ("Opening date", "date"),
        ("Opening balance", "money"), ("Notes", "text"),
    ]),
    "contracts": ("Contracts", "CON", [
        ("Name", "text"), ("User", "related", "users"),
        ("Type", "dropdown", ["Service", "Tenancy", "Other"]),
        ("Status", "dropdown", ["Draft", "Active", "Completed", "Terminated"]),
        ("Start date", "date"), ("End date", "date"), ("Value", "money"),
        ("Document URL", "text"), ("Notes", "text"),
    ]),
    "properties": ("Properties", "PRP", [
        ("Address", "text"), ("Suburb", "text"), ("Postcode", "text"),
        ("State", "dropdown", ["NSW", "ACT", "VIC", "QLD", "SA", "WA", "TAS", "NT"]),
        ("Tenants", "related_many", "users"), ("Contract", "related", "contracts"),
        ("Purchase date", "date"), ("Purchase price", "money"),
        ("Current value", "money"), ("Loan balance", "money"),
        ("Weekly rent", "money"), ("Notes", "text"),
    ]),
    "invoices": ("Invoices", "INV", [
        ("Description", "text"), ("Customer", "related", "users"),
        ("Contract", "related", "contracts"), ("Issue date", "date"), ("Due date", "date"),
        ("Status", "dropdown", ["Draft", "Sent", "Part paid", "Paid", "Cancelled"]),
        ("Amount excluding GST", "money"), ("GST amount", "money"),
        ("Reference", "text"), ("Notes", "text"),
    ]),
    "orders": ("Purchase orders", "PO", [
        ("Description", "text"), ("Supplier", "text"), ("Contract", "related", "contracts"),
        ("Order date", "date"), ("Status", "dropdown", ["Draft", "Issued", "Received", "Cancelled"]),
        ("Amount excluding GST", "money"), ("GST amount", "money"),
        ("Reference", "text"), ("Notes", "text"),
    ]),
    "stocks": ("Stocks", "STK", [
        ("Name", "text"), ("Ticker", "text"), ("Exchange", "text"),
        ("Units", "number"), ("Cost per unit", "money"), ("Price per unit", "money"),
        ("Price date", "date"), ("Bank account", "related", "accounts"), ("Notes", "text"),
    ]),
    "transactions": ("Transactions", "TRN", [
        ("Description", "text"), ("Date", "date"),
        ("Direction", "dropdown", ["Income", "Expense", "Transfer in", "Transfer out"]),
        ("Amount", "money"),
        ("Tax deductible", "dropdown", ["Yes", "No", "Review"]),
        ("Category", "dropdown", [
            "Bills", "Entertainment", "Travel", "Groceries", "Salary", "Business income",
            "Rent", "Interest", "Loan principal", "Repairs and maintenance", "Insurance",
            "Council rates", "Strata", "Water", "Land tax", "Professional fees",
            "Dividends", "Investment purchase", "Transfer", "Other",
        ]),
        ("Bank account", "related", "accounts"), ("User", "related", "users"),
        ("Property", "related", "properties"), ("Stock", "related", "stocks"),
        ("Invoice", "related", "invoices"), ("Purchase order", "related", "orders"),
        ("Contract", "related", "contracts"), ("Notes", "text"),
    ]),
}


def install_defaults(conn):
    """Add missing defaults, reusing compatible modules without changing records/views."""
    ids = {}
    for role, (name, prefix, _) in DEFINITIONS.items():
        module_id = conn.scalar(sa.select(defaults.c.module_id).where(defaults.c.role == role))
        if module_id is None:
            module_id = conn.scalar(sa.select(catalog.modules.c.id).where(catalog.modules.c.name == name))
            if module_id is None:
                module_id = catalog.create_module(conn, name, prefix + "_{n}")
            conn.execute(defaults.insert().values(role=role, module_id=module_id))
        ids[role] = module_id
    for role, (_, _, definitions) in DEFINITIONS.items():
        for label, kind, *extra in definitions:
            module = load(conn, ids[role])
            existing = next((f for f in module.fields if f.label.casefold() == label.casefold()), None)
            options = extra[0] if extra and isinstance(extra[0], list) else []
            target = ids[extra[0]] if kind in catalog.RELATED else None
            if existing:
                if (existing.label != label or existing.kind != kind or existing.target != target
                        or (options and existing.choices != options)):
                    raise Invalid(f"{module.name}: existing field '{label}' is incompatible with finance defaults.")
                continue
            form = {"label": label, "kind": kind, "choices": "\n".join(options)}
            if target:
                form["target"] = str(target)
            catalog.add_field(conn, module, form)
            field = load(conn, ids[role]).fields[-1]
            if len(module.fields) >= 6:
                conn.execute(catalog.fields.update().where(catalog.fields.c.id == field.id).values(list=None))


def finance_modules(conn):
    return {row.role: load(conn, row.module_id) for row in conn.execute(sa.select(defaults))}


def validate_record(conn, module, record_id, scalars, selections):
    role = conn.scalar(sa.select(defaults.c.role).where(defaults.c.module_id == module.id))
    if not role:
        return
    fields = {f.label: f for f in module.fields}
    old = {}
    if record_id is not None:
        table = module.table
        old = conn.execute(sa.select(table).where(table.c.id == record_id)).mappings().one()
    values = {**old, **scalars}
    selected = {link.name: items for link, items in selections}

    def value(label):
        field = fields[label]
        if field.kind in catalog.LINKED:
            link = links(field)
            return selected.get(link.name, list(conn.scalars(
                sa.select(link.c.value).where(link.c.record_id == record_id)
            )) if record_id is not None else [])
        return values.get(key(field))

    required = {
        "transactions": ["Date", "Direction", "Amount", "Tax deductible", "Category", "Bank account"],
        "accounts": ["Name", "Opening date", "Opening balance"],
        "users": ["Name", "Type"],
    }.get(role, [])
    for label in required:
        if value(label) is None or value(label) == "" or value(label) == []:
            raise Invalid(f"{label}: a value is required for this finance record.")
    numeric_labels = {label for label, kind, *_ in DEFINITIONS[role][2] if kind in {"money", "number"}}
    for field in module.fields:
        amount = values.get(key(field))
        if field.label in numeric_labels and amount is not None:
            if amount < 0 and not (role == "accounts" and field.label == "Opening balance"):
                raise Invalid(f"{field.label}: enter a non-negative amount.")
    if role == "transactions" and value("Amount") <= 0:
        raise Invalid("Amount: enter a positive amount; choose the direction separately.")
    for start, end in [("Start date", "End date"), ("Issue date", "Due date")]:
        if start in fields and value(start) and value(end) and value(end) < value(start):
            raise Invalid(f"{end}: cannot be before {start.lower()}.")
    if role in {"properties", "invoices"}:
        label, expected = ("Tenants", "Tenant") if role == "properties" else ("Customer", "Customer")
        user_module = load(conn, fields[label].target)
        user_type = next(f for f in user_module.fields if f.label == "Type")
        user_table = user_module.table
        for user_id in value(label):
            actual = conn.scalar(sa.select(user_table.c[key(user_type)]).where(user_table.c.id == user_id))
            if actual != expected:
                raise Invalid(f"{label}: select users categorised as {expected.lower()}s.")
    if role == "users" and record_id is not None:
        for other_role, label, expected in [
            ("properties", "Tenants", "Tenant"), ("invoices", "Customer", "Customer"),
        ]:
            other_id = conn.scalar(sa.select(defaults.c.module_id).where(defaults.c.role == other_role))
            if other_id:
                other = load(conn, other_id)
                field = next(f for f in other.fields if f.label == label)
                link = links(field)
                if value("Type") != expected and conn.scalar(
                    sa.select(link.c.record_id).where(link.c.value == record_id).limit(1)
                ):
                    raise Invalid(f"Type: this user is linked as a {expected.lower()}.")


ZERO = Decimal("0")


def document_total(conn, module, row):
    role = conn.scalar(sa.select(defaults.c.role).where(defaults.c.module_id == module.id))
    if role not in {"invoices", "orders"}:
        return None
    fields = {f.label: f for f in module.fields}
    amount = row[key(fields["Amount excluding GST"])]
    gst = row[key(fields["GST amount"])]
    return amount + gst if amount is not None and gst is not None else None


def data(conn, module):
    records = Records(conn, module)
    rows = records.listing({})
    related = records.values(rows, [f for f in module.fields if f.kind in catalog.LINKED], for_edit=True)
    return [
        {"id": row.id, **{
            f.label: related[row.id].get(key(f), []) if f.kind in catalog.LINKED else row[key(f)]
            for f in module.fields
        }} for row in rows
    ]


def dashboard(conn, today=None):
    today = today or datetime.now(ZoneInfo("Australia/Sydney")).date()
    month = today.replace(day=1)
    financial_year = date(today.year if today.month >= 7 else today.year - 1, 7, 1)
    modules = finance_modules(conn)
    if not modules:
        return None
    rows = {role: data(conn, module) for role, module in modules.items()}
    complete = [t for t in rows["transactions"] if all(
        t[label] is not None and t[label] != "" and t[label] != []
        for label in ["Date", "Direction", "Amount", "Tax deductible", "Category", "Bank account"]
    ) and t["Amount"] > 0]
    transactions = [t for t in complete if t["Date"] <= today]
    current = [t for t in transactions if t["Date"] >= month]

    def total(items, direction, deductible=False):
        return sum((t["Amount"] or ZERO for t in items if t["Direction"] == direction
                    and (not deductible or t["Tax deductible"] == "Yes")), ZERO)

    income, expenses = total(current, "Income"), total(current, "Expense")
    accounts = []
    for account in rows["accounts"]:
        balance = None
        if account["Opening date"] and account["Opening balance"] is not None and account["Opening date"] <= today:
            balance = account["Opening balance"]
            for t in transactions:
                if str(account["id"]) in t["Bank account"] and t["Date"] >= account["Opening date"]:
                    balance += (t["Amount"] or ZERO) * (1 if t["Direction"] in {"Income", "Transfer in"} else -1)
        accounts.append({**account, "balance": balance})
    properties = []
    users = {str(u["id"]): u["Name"] for u in rows["users"]}
    for property in rows["properties"]:
        activity = [t for t in transactions if str(property["id"]) in t["Property"] and t["Date"] >= financial_year]
        rental_income = total(activity, "Income")
        deductible_expenses = total(activity, "Expense", True)
        result = rental_income - deductible_expenses
        properties.append({
            **property, "tenants": [users[i] for i in property["Tenants"]],
            "income": rental_income, "expenses": total(activity, "Expense"),
            "deductible": deductible_expenses, "result": result,
            "cash_flow": rental_income - total(activity, "Expense"),
            "review": sum((t["Amount"] or ZERO for t in activity
                           if t["Direction"] == "Expense" and t["Tax deductible"] == "Review"), ZERO),
            "gearing": "Negative" if result < 0 else "Positive" if result > 0 else "Neutral",
        })
    stocks = []
    for stock in rows["stocks"]:
        units, price, cost = stock["Units"], stock["Price per unit"], stock["Cost per unit"]
        value = units * price if units is not None and price is not None else None
        gain = value - units * cost if value is not None and cost is not None else None
        stocks.append({**stock, "value": value, "gain": gain})
    categories = {}
    for t in current:
        if t["Direction"] == "Expense":
            category = t["Category"] or "Uncategorised"
            categories[category] = categories.get(category, ZERO) + (t["Amount"] or ZERO)
    return dict(
        today=today, month=month, financial_year=financial_year, modules=modules,
        account_filter=key(next(f for f in modules["transactions"].fields if f.label == "Bank account")),
        property_filter=key(next(f for f in modules["transactions"].fields if f.label == "Property")),
        income=income, expenses=expenses, savings=income - expenses,
        savings_rate=(income - expenses) / income * 100 if income else None,
        accounts=accounts, cash=sum((a["balance"] for a in accounts if a["balance"] is not None), ZERO),
        properties=properties, stocks=stocks, categories=sorted(categories.items()),
        incomplete=len(rows["transactions"]) - len(complete),
    )
