import secrets

import sqlalchemy as sa
from flask import (
    Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for,
)

from . import catalog
from .catalog import FIELD_TYPES, VIEWS, Invalid, key, modules
from .records import Records


web = Blueprint("builder", __name__)


@web.before_request
def open_database():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or request.form.get("_csrf") != token:
            abort(400, "Expired or missing form token. Reload the page and try again.")
    g.conn = current_app.extensions["builder_engine"].connect()


@web.teardown_request
def close_database(_error):
    if "conn" in g:
        g.conn.close()


@web.context_processor
def navigation():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return dict(
        nav=g.conn.execute(sa.select(modules).order_by(modules.c.name)).all(),
        types=FIELD_TYPES, views=VIEWS, key=key, csrf=session["csrf"],
    )


def module_or_404(module_id):
    try:
        return catalog.load(g.conn, module_id)
    except LookupError:
        abort(404, "Module not found.")


@web.get("/")
def home():
    first = g.conn.scalar(sa.select(modules.c.id).order_by(modules.c.name).limit(1))
    if first is None:
        return redirect(url_for(".settings"))
    return redirect(url_for(".listing", module_id=first))


@web.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            module_id = catalog.create_module(
                g.conn, request.form.get("name", ""), request.form.get("pattern", "")
            )
        except Invalid as exc:
            return render_template("settings.html", error=str(exc)), 400
        g.conn.commit()
        return redirect(url_for(".design", module_id=module_id))
    return render_template("settings.html")


@web.route("/settings/<int:module_id>", methods=["GET", "POST"])
def design(module_id):
    module = module_or_404(module_id)
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "field":
                catalog.add_field(g.conn, module, request.form)
            elif action == "layout":
                catalog.save_layout(g.conn, module, request.form)
            else:
                abort(400, "Unknown builder action.")
        except Invalid as exc:
            g.conn.rollback()
            return render_template("design.html", module=module, error=str(exc)), 400
        g.conn.commit()
        return redirect(url_for(".design", module_id=module_id))
    return render_template("design.html", module=module)


@web.get("/modules/<int:module_id>")
def listing(module_id):
    module = module_or_404(module_id)
    records = Records(g.conn, module)
    columns = module.layout("list")
    try:
        rows = records.listing(request.args)
    except Invalid as exc:
        abort(400, str(exc))
    return render_template(
        "list.html", module=module, rows=rows, columns=columns,
        values=records.values(rows, columns), options=records.options,
    )


@web.get("/modules/<int:module_id>/<int:record_id>")
def detail(module_id, record_id):
    module = module_or_404(module_id)
    records = Records(g.conn, module)
    row = g.conn.execute(sa.select(records.table).where(records.table.c.id == record_id)).mappings().first()
    if row is None:
        abort(404, "Record not found.")
    visible = module.layout("detail")
    return render_template(
        "detail.html", module=module, row=row, visible=visible,
        values=records.values([row], visible)[record_id],
    )


@web.route("/modules/<int:module_id>/new", defaults={"record_id": None}, methods=["GET", "POST"])
@web.route("/modules/<int:module_id>/<int:record_id>/edit", methods=["GET", "POST"])
def edit(module_id, record_id):
    module = module_or_404(module_id)
    records = Records(g.conn, module)
    visible = module.layout("edit")
    values, error = {}, None
    if request.method == "POST":
        try:
            saved = records.write(record_id, request.form)
        except LookupError:
            abort(404, "Record not found.")
        except Invalid as exc:
            error = str(exc)
            values = {key(f): request.form.getlist(key(f)) for f in visible}
        else:
            g.conn.commit()
            return redirect(url_for(".detail", module_id=module_id, record_id=saved))
    elif record_id is not None:
        row = g.conn.execute(sa.select(records.table).where(records.table.c.id == record_id)).mappings().first()
        if row is None:
            abort(404, "Record not found.")
        values = records.values([row], visible, for_edit=True)[record_id]
    return render_template(
        "edit.html", module=module, record_id=record_id, visible=visible,
        values=values, options=records.options, error=error,
    ), 400 if error else 200
