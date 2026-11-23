"""Standalone Flask entry point for the metadata-driven single-user UI."""

import os
import secrets
from pathlib import Path

import sqlalchemy as sa
from flask import Flask

from .catalog import metadata


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.environ.get("DATABASE_URL"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    )
    app.config.update(config or {})
    uri = app.config["DATABASE_URL"]
    if not uri:
        directory = Path(app.instance_path)
        directory.mkdir(parents=True, exist_ok=True)
        uri = f"sqlite:///{directory / 'finance.sqlite3'}"
    engine = sa.create_engine(uri)
    if engine.dialect.name == "sqlite":
        # sqlite3's legacy transaction mode otherwise commits some DDL immediately.
        @sa.event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")

        @sa.event.listens_for(engine, "begin")
        def begin_sqlite(connection):
            connection.exec_driver_sql("BEGIN")

    metadata.create_all(engine)
    app.extensions["builder_engine"] = engine
    from .web import web

    app.register_blueprint(web)
    return app
