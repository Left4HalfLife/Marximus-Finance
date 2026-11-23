# Marximus-Finance
A modular, metadata-driven CRM-style web application built for Finance.
Major credit design to [SuiteCRM](https://docs.suitecrm.com/developer/database-schema/)

## Overview
Define modules, fields, relationships and views in **Settings → Module builder**.
The app starts empty and is intended for one user on a trusted local machine.
There is no sign-in or permission system.

## Run locally

With Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app.modules.builder run
```

Open **http://localhost:5000/settings**. Without `DATABASE_URL`, the app stores
data in `instance/finance.sqlite3`. To use the supplied PostgreSQL 16 setup
instead, run `docker compose up --build` and open the same URL. PostgreSQL data
persists in the Compose volume. The sample `.env.example` database URL is for
use **inside** the Compose network, not for the local SQLite setup. Compose
publishes ports 5000 and 5432; do not expose this unauthenticated development
setup to an untrusted network.

## Example: tag and find transactions

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

Run the integration tests with `python -m unittest discover -v`. They use
temporary SQLite databases, not the configured finance database.
