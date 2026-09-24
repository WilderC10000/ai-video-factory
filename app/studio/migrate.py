"""Minimal additive migrations for studio_* tables (no Alembic in this repo yet).

create_all() creates missing tables but never adds columns to existing ones, so
each nullable column added after a table first shipped is listed here and added
with ALTER TABLE if absent. Additive only: nothing is dropped or rewritten.
"""
from sqlalchemy import Engine, inspect, text

_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "studio_approvals": {"output_completed_at": "DATETIME"},
}


def ensure_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
