"""Row-level security verification at the database layer.

Phase 1 exit criterion: a cross-tenant query attempt returns nothing. These
tests run real SQL as the RLS-enforced app role against real Postgres — the
isolation is proven at the database, not trusted to application code.
"""

import psycopg
import pytest


def _create_firm(db, name: str) -> str:
    with db.admin() as conn:
        row = conn.execute(
            "INSERT INTO firms (name) VALUES (%s) RETURNING id", (name,)
        ).fetchone()
    return str(row["id"])


@pytest.fixture
def two_firms(db):
    firm_a = _create_firm(db, "Firm A")
    firm_b = _create_firm(db, "Firm B")
    with db.firm(firm_a) as conn:
        conn.execute(
            "INSERT INTO contacts (firm_id, name, phone) VALUES (%s, 'Alice A', '+1111')",
            (firm_a,),
        )
    with db.firm(firm_b) as conn:
        conn.execute(
            "INSERT INTO contacts (firm_id, name, phone) VALUES (%s, 'Bob B', '+2222')",
            (firm_b,),
        )
    return firm_a, firm_b


def test_firm_sees_only_its_own_rows(db, two_firms):
    firm_a, firm_b = two_firms
    with db.firm(firm_a) as conn:
        rows = conn.execute("SELECT name FROM contacts").fetchall()
    assert [r["name"] for r in rows] == ["Alice A"]
    with db.firm(firm_b) as conn:
        rows = conn.execute("SELECT name FROM contacts").fetchall()
    assert [r["name"] for r in rows] == ["Bob B"]


def test_cross_tenant_query_returns_nothing(db, two_firms):
    firm_a, firm_b = two_firms
    with db.firm(firm_a) as conn:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE firm_id = %s", (firm_b,)
        ).fetchall()
    assert rows == []  # even an explicit cross-tenant WHERE returns nothing


def test_no_context_returns_nothing(db, two_firms):
    # An app-role connection with no firm context set must see zero rows.
    with db._app_pool.connection() as conn:  # deliberately bypass db.firm()
        rows = conn.execute("SELECT * FROM contacts").fetchall()
    assert rows == []


def test_cross_tenant_write_is_rejected(db, two_firms):
    firm_a, firm_b = two_firms
    with pytest.raises(psycopg.Error, match="row-level security"):
        with db.firm(firm_a) as conn:
            conn.execute(
                "INSERT INTO contacts (firm_id, name) VALUES (%s, 'Mallory')", (firm_b,)
            )


def test_firms_table_hides_other_firms_and_credentials(db, two_firms):
    firm_a, firm_b = two_firms
    with db.admin() as conn:
        conn.execute(
            "UPDATE firms SET cms_credentials_enc = 'ciphertext-b' WHERE id = %s", (firm_b,)
        )
    with db.firm(firm_a) as conn:
        rows = conn.execute("SELECT id, cms_credentials_enc FROM firms").fetchall()
    assert [str(r["id"]) for r in rows] == [firm_a]


def test_app_role_cannot_read_tokens_or_delete(db, two_firms):
    firm_a, _ = two_firms
    with pytest.raises(psycopg.Error):
        with db.firm(firm_a) as conn:
            conn.execute("SELECT * FROM firm_tokens").fetchall()
    with pytest.raises(psycopg.Error, match="permission denied"):
        with db.firm(firm_a) as conn:
            conn.execute("DELETE FROM contacts")


def test_events_are_append_only_for_app_role(db, two_firms):
    firm_a, _ = two_firms
    with db.firm(firm_a) as conn:
        conn.execute(
            "INSERT INTO events (firm_id, type, payload) VALUES (%s, 'test.event', '{}')",
            (firm_a,),
        )
    with pytest.raises(psycopg.Error, match="permission denied"):
        with db.firm(firm_a) as conn:
            conn.execute("UPDATE events SET status = 'processed'")
