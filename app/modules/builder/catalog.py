"""Metadata and additive DDL for the module builder (SQLite and PostgreSQL)."""

from dataclasses import dataclass

import sqlalchemy as sa


FIELD_TYPES = {
    "text": "Free text",
    "date": "Date",
    "radio": "Radio buttons",
    "dropdown": "Dropdown",
    "multi": "Multi-select dropdown",
    "related": "Related record",
    "related_many": "Related records (multi-select)",
}
CHOICES = {"radio", "dropdown", "multi"}
RELATED = {"related", "related_many"}
LINKED = RELATED | {"multi"}
VIEWS = ("list", "detail", "edit")

metadata = sa.MetaData()
modules = sa.Table(
    "builder_modules", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String(100), nullable=False, unique=True),
    sa.Column("pattern", sa.String(100), nullable=False),
)
fields = sa.Table(
    "builder_fields", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("module_id", sa.ForeignKey(modules.c.id), nullable=False),
    sa.Column("label", sa.String(100), nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("choices", sa.JSON, nullable=False),
    sa.Column("target", sa.ForeignKey(modules.c.id)),
    *(sa.Column(view, sa.Integer) for view in VIEWS),
    sa.Column("searchable", sa.Boolean, nullable=False),
    sa.Column("filterable", sa.Boolean, nullable=False),
    sa.UniqueConstraint("module_id", "label"),
)


class Invalid(ValueError):
    """A builder or record form needs correcting before it can be saved."""


def key(field):
    return f"f_{field.id}"


def base_table(module_id, md):
    name = f"builder_records_{module_id}"
    if name not in md.tables:
        sa.Table(name, md, sa.Column("id", sa.Integer, primary_key=True))
    return md.tables[name]


def links(field):
    md = sa.MetaData()
    source = base_table(field.module_id, md)
    if field.kind in RELATED:
        target_type = sa.ForeignKey(base_table(field.target, md).c.id)
    else:
        target_type = sa.Text
    return sa.Table(
        f"builder_links_{field.id}", md,
        sa.Column("record_id", sa.ForeignKey(source.c.id), primary_key=True),
        sa.Column("value", target_type, primary_key=True),
        *([sa.UniqueConstraint("record_id")] if field.kind == "related" else []),
    )


@dataclass
class Module:
    id: int
    name: str
    pattern: str
    fields: list

    @property
    def table(self):
        table = base_table(self.id, sa.MetaData())
        for field in self.fields:
            if field.kind not in LINKED:
                table.append_column(sa.Column(key(field), scalar_type(field.kind)))
        return table

    def layout(self, view):
        return sorted(
            (f for f in self.fields if f[view] is not None),
            key=lambda f: (f[view], f.id),
        )

    def number(self, row_id):
        return self.pattern.replace("{n}", str(row_id - 1))


def scalar_type(kind):
    return sa.Date if kind == "date" else sa.Text


def load(conn, module_id):
    row = conn.execute(sa.select(modules).where(modules.c.id == module_id)).first()
    if row is None:
        raise LookupError("Module not found.")
    definitions = conn.execute(
        sa.select(fields).where(fields.c.module_id == module_id).order_by(fields.c.id)
    ).mappings().all()
    return Module(row.id, row.name, row.pattern, definitions)


def label(value):
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise Invalid("Enter a name between 1 and 100 characters.")
    return value


def create_module(conn, name, pattern):
    name, pattern = label(name), pattern.strip()
    if pattern.count("{n}") != 1 or len(pattern) > 100:
        raise Invalid("Use {n} once in a record pattern of up to 100 characters.")
    if conn.scalar(sa.select(modules.c.id).where(modules.c.name == name)):
        raise Invalid("A module with that name already exists.")
    module_id = conn.execute(
        modules.insert().values(name=name, pattern=pattern)
    ).inserted_primary_key[0]
    base_table(module_id, sa.MetaData()).create(conn)
    return module_id


def add_field(conn, module, form):
    name = label(form.get("label", ""))
    kind = form.get("kind")
    if kind not in FIELD_TYPES:
        raise Invalid("Choose a supported field type.")
    if any(f.label.casefold() == name.casefold() for f in module.fields):
        raise Invalid("A field with that name already exists.")
    options, target = [], None
    if kind in CHOICES:
        options = list(dict.fromkeys(
            line.strip() for line in form.get("choices", "").splitlines() if line.strip()
        ))
        if not options:
            raise Invalid("Enter at least one choice, one per line.")
    if kind in RELATED:
        raw = form.get("target", "")
        try:
            target = int(raw)
        except ValueError:
            raise Invalid("Select an existing target module.") from None
        if not conn.scalar(sa.select(modules.c.id).where(modules.c.id == target)):
            raise Invalid("Select an existing target module.")
    positions = {v: max((f[v] or 0 for f in module.fields), default=0) + 1 for v in VIEWS}
    field_id = conn.execute(fields.insert().values(
        module_id=module.id, label=name, kind=kind, choices=options, target=target,
        searchable=True, filterable=kind != "text", **positions,
    )).inserted_primary_key[0]
    field = conn.execute(sa.select(fields).where(fields.c.id == field_id)).one()
    if kind in LINKED:
        links(field).create(conn)
    else:
        # Identifiers are derived only from database-assigned integer IDs.
        column_type = scalar_type(kind)().compile(dialect=conn.dialect)
        conn.exec_driver_sql(
            f"ALTER TABLE {module.table.name} ADD COLUMN {key(field)} {column_type}"
        )


def save_layout(conn, module, form):
    for field in module.fields:
        settings = {}
        for view in VIEWS:
            value = form.get(f"{view}_{field.id}", "").strip()
            if not value:
                settings[view] = None
            elif value.isascii() and value.isdigit() and len(value) <= 6 and int(value) > 0:
                settings[view] = int(value)
            else:
                raise Invalid("Use positions from 1 to 999999, or leave blank to hide a field.")
        for flag in ("searchable", "filterable"):
            settings[flag] = f"{flag}_{field.id}" in form
        conn.execute(fields.update().where(fields.c.id == field.id).values(**settings))
