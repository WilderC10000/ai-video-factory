"""Test setup: point the app at a throwaway SQLite file in a temp directory so
tests never touch the real data/videofactory.db, then recreate tables fresh
before every test for isolation.
"""
import os
import tempfile

_TEST_DIR = tempfile.mkdtemp(prefix="aivideofactory_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/test.db"
os.environ["PROJECT_DATA_DIR"] = f"{_TEST_DIR}/projects"

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
import app.models.project  # noqa: E402,F401  (register models on Base)
import app.models.video_job  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c
