import os
import shutil
import socket
import subprocess

import pytest
from fastapi.testclient import TestClient

from api.main import PlatformContext, create_app

# ---------------------------------------------------------------------------
# Phase 0 fixtures (SQLite prototype endpoints)
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Phase 1 fixtures: ephemeral Postgres (real RLS, zero footprint), platform app
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_pg_binaries() -> tuple[str | None, str | None]:
    """Locate full Postgres *server* binaries. PATH may only carry libpq's
    client tools (Homebrew), so check bindirs that also ship `postgres`."""
    import glob

    candidates: list[str] = []
    if os.getenv("CASELINE_PG_BIN"):
        candidates.append(os.environ["CASELINE_PG_BIN"])
    which = shutil.which("initdb")
    if which:
        candidates.append(os.path.dirname(which))
    candidates += sorted(glob.glob("/opt/homebrew/opt/postgresql@*/bin"), reverse=True)
    candidates += sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)
    for bindir in candidates:
        if all(os.path.exists(os.path.join(bindir, b)) for b in ("initdb", "pg_ctl", "postgres")):
            return os.path.join(bindir, "initdb"), os.path.join(bindir, "pg_ctl")
    return None, None


@pytest.fixture(scope="session")
def pg_admin_dsn(tmp_path_factory):
    """A throwaway Postgres server for the test session.

    Uses CASELINE_TEST_ADMIN_DSN if provided (CI); otherwise initdb's a
    fresh cluster with trust auth on a unix socket — real Postgres, real
    RLS, no credentials, no state left behind."""
    external = os.getenv("CASELINE_TEST_ADMIN_DSN")
    if external:
        yield external
        return
    initdb, pg_ctl = _find_pg_binaries()
    if not (initdb and pg_ctl):
        pytest.skip("Postgres server binaries (initdb/pg_ctl/postgres) not available")
    import tempfile

    datadir = str(tmp_path_factory.mktemp("pgdata"))
    # macOS caps unix socket paths at 104 chars; pytest tmp dirs blow past
    # it, so the socket lives in a short-lived /tmp dir instead.
    sockdir = tempfile.mkdtemp(prefix="caseline-pg-")
    subprocess.run(
        [initdb, "-D", datadir, "-U", "caseline_owner", "--auth=trust", "--no-sync"],
        check=True,
        capture_output=True,
    )
    port = _free_port()
    subprocess.run(
        [
            pg_ctl, "start", "-D", datadir, "-w", "-l", f"{datadir}/pg.log",
            "-o", f"-p {port} -k {sockdir} -c listen_addresses=''",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield f"host={sockdir} port={port} user=caseline_owner dbname=postgres"
    finally:
        subprocess.run(
            [pg_ctl, "stop", "-D", datadir, "-m", "immediate"], capture_output=True
        )
        shutil.rmtree(sockdir, ignore_errors=True)


_TENANT_TABLES = (
    "referrals, referral_partners, lead_reviews, voice_profiles,"
    " idempotency_keys, turn_metrics, events, consults, messages, tasks, matters,"
    " leads, transcripts, calls, contacts, agents, firm_tokens, firms"
)


@pytest.fixture(scope="session")
def platform_db(pg_admin_dsn):
    """Migrated Database against a dedicated test db (session-scoped)."""
    import psycopg

    from api.platform.db import Database

    with psycopg.connect(pg_admin_dsn, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS caseline_test")
        conn.execute("CREATE DATABASE caseline_test")
    info = psycopg.conninfo.conninfo_to_dict(pg_admin_dsn)
    info["dbname"] = "caseline_test"
    db = Database(psycopg.conninfo.make_conninfo(**info))
    db.migrate()
    yield db
    db.close()


@pytest.fixture
def db(platform_db):
    """Function-scoped clean slate on the session database."""
    with platform_db.admin() as conn:
        conn.execute(f"TRUNCATE {_TENANT_TABLES} RESTART IDENTITY CASCADE")
    return platform_db


ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def platform(db):
    from api.messaging import LoggingSMSProvider
    from api.platform.auth import RateLimiter
    from api.platform.secrets import FernetCipher
    from api.platform.session_state import InMemorySessionStore

    return PlatformContext(
        db=db,
        session_store=InMemorySessionStore(),
        sms=LoggingSMSProvider(),
        cipher=FernetCipher(FernetCipher.generate_key()),
        rate_limiter=RateLimiter(limit=10_000),
        admin_token=ADMIN_TOKEN,
    )


@pytest.fixture
def v1_app(tmp_path, platform):
    return create_app(db_path=str(tmp_path / "test.db"), platform=platform)


@pytest.fixture
def v1_client(v1_app):
    with TestClient(v1_app) as c:
        yield c


@pytest.fixture
def firm(v1_client):
    """A fully onboarded simulated firm: returns dict with ids + auth headers."""
    r = v1_client.post(
        "/v1/admin/firms",
        json={
            "name": "Bluebonnet Injury Law",
            "timezone": "America/Chicago",
            "cms_provider": "mock",
            "practice_area": "personal injury",
            "transfer_number": "+15125550199",
        },
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    data["headers"] = {"Authorization": f"Bearer {data['token']}"}
    return data


@pytest.fixture
def second_firm(v1_client):
    r = v1_client.post(
        "/v1/admin/firms",
        json={"name": "Rival Firm LLP", "cms_provider": "mock"},
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    data["headers"] = {"Authorization": f"Bearer {data['token']}"}
    return data
