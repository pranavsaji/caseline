import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
