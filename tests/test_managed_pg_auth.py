"""Managed-Postgres auth for the RLS app role (Railway/RDS-class hosts).

Locally the app role rides trust/peer auth; managed Postgres requires a
password. CASELINE_APP_DB_PASSWORD drives both halves: migrate() assigns it
to the role, and _app_dsn() carries it on app-role connections."""

from api.platform.db import APP_ROLE, _app_dsn


def test_app_dsn_drops_password_by_default(monkeypatch):
    monkeypatch.delenv("CASELINE_APP_DB_PASSWORD", raising=False)
    dsn = _app_dsn("host=db.example.com user=owner password=admin-secret dbname=caseline")
    assert f"user={APP_ROLE}" in dsn
    assert "admin-secret" not in dsn and "password" not in dsn


def test_app_dsn_uses_app_password_when_configured(monkeypatch):
    monkeypatch.setenv("CASELINE_APP_DB_PASSWORD", "app-role-secret")
    dsn = _app_dsn("host=db.example.com user=owner password=admin-secret dbname=caseline")
    assert f"user={APP_ROLE}" in dsn
    assert "password=app-role-secret" in dsn
    assert "admin-secret" not in dsn  # the owner password never leaks across roles


def test_migrate_assigns_role_password(platform_db, monkeypatch):
    monkeypatch.setenv("CASELINE_APP_DB_PASSWORD", "migrate-set-secret")
    platform_db.migrate()  # idempotent re-run; assigns/rotates the password
    with platform_db.admin() as conn:
        row = conn.execute(
            "SELECT rolpassword IS NOT NULL AS has_password, rolcanlogin"
            " FROM pg_authid WHERE rolname = %s",
            (APP_ROLE,),
        ).fetchone()
    assert row["has_password"] and row["rolcanlogin"]
