from datetime import date
from functools import cached_property

import sqlalchemy as sa

from .catalog import CHOICES, LINKED, RELATED, Invalid, key, links, load


def number_expression(module, table):
    prefix, suffix = module.pattern.split("{n}")
    return sa.literal(prefix) + sa.cast(table.c.id - 1, sa.String) + suffix


class Records:
    def __init__(self, conn, module):
        self.conn = conn
        self.module = module
        self.table = module.table
        self._targets = {}

    def target(self, field):
        if field.target not in self._targets:
            module = load(self.conn, field.target)
            table = module.table.alias()
            number = number_expression(module, table)
            name = next((f for f in module.fields if f.kind == "text"), None)
            caption = number
            if name:
                text = sa.func.nullif(table.c[key(name)], "")
                caption = sa.func.coalesce(text + " (" + number + ")", number)
            self._targets[field.target] = table, caption
        return self._targets[field.target]

    def options(self, field):
        if field.kind not in RELATED:
            return [(value, value) for value in field.choices]
        table, caption = self.target(field)
        return [(str(i), name) for i, name in self.conn.execute(
            sa.select(table.c.id, caption).order_by(caption, table.c.id)
        )]

    def require(self, record_id):
        if not self.conn.scalar(sa.select(self.table.c.id).where(self.table.c.id == record_id)):
            raise LookupError("Record not found.")

    def write(self, record_id, form):
        if record_id is not None:
            self.require(record_id)
        scalars, selections = {}, []
        for field in self.module.layout("edit"):
            # Only fields in the saved edit layout participate in this update.
            values = list(dict.fromkeys(v for v in form.getlist(key(field)) if v != ""))
            if field.kind not in {"multi", "related_many"} and len(values) > 1:
                raise Invalid(f"{field.label}: select only one value.")
            if field.kind in CHOICES and any(v not in field.choices for v in values):
                raise Invalid(f"{field.label}: select a listed choice.")
            if field.kind in RELATED and values:
                if any(not v.isascii() or not v.isdecimal() or len(v) > 10 for v in values):
                    raise Invalid(f"{field.label}: select an existing record.")
                values = list(dict.fromkeys(map(int, values)))
                target, _ = self.target(field)
                found = self.conn.scalars(sa.select(target.c.id).where(target.c.id.in_(values)))
                if set(found) != set(values):
                    raise Invalid(f"{field.label}: selected record does not exist.")
            if field.kind in LINKED:
                selections.append((links(field), values))
            else:
                value = values[0] if values else None
                if value and field.kind == "date":
                    try:
                        value = date.fromisoformat(value)
                    except ValueError:
                        raise Invalid(f"{field.label}: enter a valid date.") from None
                scalars[key(field)] = value
        if record_id is None:
            record_id = self.conn.execute(
                self.table.insert().values(**scalars)
            ).inserted_primary_key[0]
        elif scalars:
            self.conn.execute(
                self.table.update().where(self.table.c.id == record_id).values(**scalars)
            )
        for link, values in selections:
            self.conn.execute(link.delete().where(link.c.record_id == record_id))
            if values:
                self.conn.execute(link.insert(), [
                    {"record_id": record_id, "value": v} for v in values
                ])
        return record_id

    @cached_property
    def number_column(self):
        return number_expression(self.module, self.table)

    def predicate(self, field, term, *, exact):
        if field.kind not in LINKED:
            column = sa.cast(self.table.c[key(field)], sa.String)
            return column == term if exact else column.icontains(term, autoescape=True)
        link = links(field)
        sub = sa.select(link.c.record_id)
        column = link.c.value
        if field.kind in RELATED:
            if exact:
                if not term.isascii() or not term.isdigit() or len(term) > 10:
                    raise Invalid(f"{field.label}: choose a target record.")
                term = int(term)
            else:
                target, column = self.target(field)
                sub = sub.join_from(link, target, link.c.value == target.c.id)
        condition = column == term if exact else column.icontains(term, autoescape=True)
        return self.table.c.id.in_(sub.where(condition))

    def listing(self, args):
        query = sa.select(self.table)
        term = args.get("q", "").strip()
        if term:
            query = query.where(sa.or_(
                self.number_column.icontains(term, autoescape=True),
                *(self.predicate(f, term, exact=False) for f in self.module.fields if f.searchable),
            ))
        for f in self.module.fields:
            if f.filterable and args.get(key(f)):
                query = query.where(self.predicate(f, args[key(f)], exact=True))
        order = self.table.c.id
        if args.get("sort") == "desc":
            order = order.desc()
        return self.conn.execute(query.order_by(order)).mappings().all()

    def values(self, rows, visible, *, for_edit=False):
        """Resolve selections in batches, including self-referencing fields."""
        result = {r.id: {} for r in rows}
        if not rows:
            return result
        for f in visible:
            k = key(f)
            if f.kind not in LINKED:
                for row in rows:
                    value = row[k]
                    result[row.id][k] = [] if value is None else [str(value)]
                continue
            link = links(f)
            source, value = link.c.record_id, link.c.value
            query = sa.select(source, value)
            if f.kind in RELATED and not for_edit:
                target, caption = self.target(f)
                query = sa.select(source, caption).join_from(link, target, value == target.c.id)
            for record_id, item in self.conn.execute(
                query.where(source.in_(result.keys())).order_by(source, value)
            ):
                result[record_id].setdefault(k, []).append(str(item))
        return result
