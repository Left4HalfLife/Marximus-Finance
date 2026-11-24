# Marximus-Finance
A modular, metadata-driven CRM-style web application built for Finance.
Major credit design to [SuiteCRM](https://docs.suitecrm.com/developer/database-schema/)

## Overview
Define modules, fields, relationships and views in **Settings → Module builder**.
New databases start with linked Australian finance modules and a home dashboard.
The app is intended for one user on a trusted local machine.
There is no sign-in or permission system.

## Run locally

With Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app.modules.builder run
```

Open **http://localhost:5000/** (dashboard) or **/settings** (module builder).
Without `DATABASE_URL`, the app stores
data in `instance/finance.sqlite3`. To use the supplied PostgreSQL 16 setup
instead, run `docker compose up --build` and open the same URL. PostgreSQL data
persists in the Compose volume. The sample `.env.example` database URL is for
use **inside** the Compose network, not for the local SQLite setup. Compose
publishes ports 5000 and 5432; do not expose this unauthenticated development
setup to an untrusted network.

## Default finance workspace

| Module | Tracks |
| --- | --- |
| Transactions | Date, positive AUD amount, income/expense or transfer direction, deductible status (Yes/No/Review), category, bank account and links to users, property, stocks, invoices, purchase orders and contracts |
| Bank accounts | Institution, BSB/reference, opening date and opening balance (including overdrafts) |
| Users | Customers or tenants, contact details and optional ABN; these are contacts, not application logins |
| Contracts | Customer/tenant, service/tenancy type, status, dates, value and document URL |
| Invoices | Customer, contract, issue/due dates, status, amounts excluding GST and GST, calculated total |
| Purchase orders | Supplier, contract, date, status, amounts excluding GST and GST, calculated total |
| Properties | Address/state, tenants, tenancy contract, purchase/current value, loan balance and weekly rent |
| Stocks | Ticker/exchange, fractional units, cost/current price in AUD and valuation date |

Defaults install automatically only on an empty database. For an existing builder
database, use **Settings → Install finance defaults**. Installation is additive and
repeatable: compatible existing modules are reused, records and existing layouts
are preserved, and incompatible fields produce an error with no partial install.
To deliberately start with an empty builder in code, pass
`{"FINANCE_DEFAULTS": False}` to `create_app`.

The home dashboard reports month-to-date income, expenses, net savings/cash flow,
savings rate, expenses by category and cash on hand using Sydney's date. Bank
balances equal the opening balance plus income/transfers in minus expenses/transfers
out **on or after the opening date**, up to today. Set the opening balance immediately
before transactions on that date; earlier history is not counted again. Transfers
require two entries against the respective accounts and do not count as income or
expenses. Future transactions do not affect current reports. Incomplete legacy
transactions are excluded with a warning; accounts without opening values or with
future opening dates are shown as unavailable, not as zero balances.

Property summaries use the Australian financial year (1 July to 30 June).
Cash flow is linked income minus all linked expenses; estimated rental result/gearing
is linked income minus expenses marked deductible **Yes**. Expenses marked
**Review** are shown separately. This is a tracking estimate, not tax advice:
deductibility, NSW land tax, depreciation, capital works, mixed use and ownership
apportionment must be confirmed separately with a qualified adviser. Stock values
are manual AUD valuations, not live market prices or capital gains tax calculations.

Invoices/orders do not create transactions or automatically change status. Enter
GST explicitly where applicable (zero when none applies); totals require both
amounts. These modules are registers, not compliant tax-invoice generators or BAS
calculators. Numeric fields accept up to two decimal places for money and four
for quantities.

### Investor example

Create a bank account with an opening date/balance, then a **User** of type
**Tenant**. Create a **Property** in NSW and select that tenant, optionally linking
a tenancy **Contract**. Record rent as income and interest, rates, repairs and loan
principal as separate expenses linked to the property and bank account. Mark
deductibility according to your circumstances; do not mark loan principal deductible.
The dashboard shows tenants, rental cash flow, expenses needing review and
estimated positive/negative gearing.

### Sole trader example

Create a **User** of type **Customer**, then a service **Contract** and **Invoice**
linked to them. Enter the invoice amounts and GST if applicable. When paid, create
an income **Transaction** linked to the invoice, contract, customer and bank
account, then update the invoice status. Use **Purchase orders** to track supplier
commitments and link actual expense transactions when paid.

## Builder example: tag and find transactions

On the default workspace, use its existing Transactions module and add a Tags
field. The following steps also work with an empty custom builder:

1. In Settings create **Tags**, pattern `TAG_{n}`, and add a free-text **Name**
   field. Open Tags from the navbar and create records named `Rent` and `Mortgage`.
2. Create **Transactions**, pattern `TRN_{n}`. Add a **Date** field and a
   **Tags** field of type **Related records (multi-select)** targeting Tags.
   Use **Related record** instead for a single selection; use a fixed dropdown,
   multi-select or radio field for choices that are not records.
3. In the **View editor**, set positions for list columns, detail fields and
   edit inputs. Blank positions hide fields without deleting their values.
   Enable **Searchable** and **Filterable** for Tags, then save the views.
4. Open Transactions, create a record, and select Rent. Search `rent` in the
   list or filter by the Rent record. Click the transaction number to view or
   edit it. Number sorting uses the integer ID, so `TRN_2` precedes `TRN_10`.

## Architecture

The runnable Flask package is `app/modules/builder`. `catalog.py` stores module
and field definitions (including view positions) in SQLAlchemy tables.
Creating a module creates a record table; adding a scalar field adds a nullable
column, preserving existing records. Multi-selects and relationships use
per-field link tables, with foreign keys for related records. Metadata and
schema changes are committed together. Database identifiers are derived from
integer IDs, never from user-supplied labels.

`records.py` uses those definitions for validation, writes, search and filters.
Relationships store IDs and display the target's first free-text field plus
its record number, so renaming a tag updates its display and search results
without changing any links. `web.py` serves the Settings and record screens.
The builder is additive: it does not drop modules or change existing field types.

`finance.py` provisions defaults through the same catalog APIs and records their
module IDs in `finance_defaults`. Finance validation and dashboard calculations
use the stored metadata and record/link tables, not a separate ledger. Money and
quantity fields use Decimal validation/arithmetic, PostgreSQL numeric columns and
exact decimal text storage on SQLite to avoid floating-point loss.
Relationships on detail screens link to the target record.

Run the integration tests with `python -m unittest discover -v`. They use
temporary SQLite databases, not the configured finance database.
