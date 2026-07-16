"""Postgres access layer: connection pools, migrations, tenant context.

Two pools, two trust levels:

  * ``admin()`` — the owner/platform role. Bypasses RLS (table owner). Used
    only for migrations, token auth lookup, firm onboarding, and the event
    worker. Never handed to request-path tenant code.
  * ``firm(firm_id)`` — the ``caseline_app`` role with ``SET LOCAL
    app.firm_id`` applied inside the transaction. RLS makes cross-tenant
    reads return nothing and cross-tenant writes raise. Every tenant-scoped
    query in the API goes through this and only this.

Migrations are plain SQL files in ``api/platform/migrations``, applied in
filename order and tracked in ``schema_migrations``.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger("caseline.platform.db")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
APP_ROLE = "caseline_app"


def _app_dsn(admin_dsn: str) -> str:
    """Derive the RLS-enforced DSN by swapping the user onto the app role."""
    info = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    info["user"] = APP_ROLE
    info.pop("password", None)  # app role auth is trust/peer locally, IAM in GCP
    return psycopg.conninfo.make_conninfo(**info)


class Database:
    def __init__(self, admin_dsn: str, app_dsn: str | None = None, pool_size: int = 4):
        self._admin_pool = ConnectionPool(
            admin_dsn, min_size=1, max_size=pool_size, kwargs={"row_factory": dict_row}, open=True
        )
        self._app_pool = ConnectionPool(
            app_dsn or _app_dsn(admin_dsn),
            min_size=1,
            max_size=pool_size,
            kwargs={"row_factory": dict_row},
            open=False,  # opened lazily: the app role only exists after migration 0001
        )

    # --- lifecycle ---

    def migrate(self) -> list[str]:
        """Apply pending migrations in order; returns the names applied."""
        applied: list[str] = []
        with self.admin() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {
                r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()
            }
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                logger.info("applying migration %s", path.name)
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
                applied.append(path.name)
        return applied

    def close(self) -> None:
        self._admin_pool.close()
        self._app_pool.close()

    # --- connections ---

    @contextmanager
    def admin(self) -> Iterator[psycopg.Connection]:
        """Platform-role connection (bypasses RLS). One transaction per block."""
        with self._admin_pool.connection() as conn:
            yield conn

    @contextmanager
    def firm(self, firm_id: str) -> Iterator[psycopg.Connection]:
        """Tenant-scoped connection: RLS-enforced role + firm context.

        ``SET LOCAL`` scopes the setting to this transaction, so pooled
        connections can never leak one firm's context into another's query.
        """
        if not firm_id:
            raise ValueError("firm_id is required for a tenant-scoped connection")
        if self._app_pool.closed:
            self._app_pool.open()
        with self._app_pool.connection() as conn:
            # SET LOCAL cannot take bind params; set_config(..., is_local=true)
            # is the parameterizable equivalent.
            conn.execute("SELECT set_config('app.firm_id', %s, true)", (str(firm_id),))
            yield conn
