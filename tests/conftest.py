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


IDEA = "He buried a pink submarine in his backyard and turned it into an underground luxury bunker."


@pytest.fixture()
def ready_shot(db_session):
    """A project taken all the way to STORYBOARD_READY, returning its first
    shot (status PROMPT_READY) - the starting point most generation tests need."""
    from app.providers.llm.mock import MockLLMProvider
    from app.services import project_service

    llm = MockLLMProvider()
    project = project_service.create_project(db_session, IDEA)
    project = project_service.advance_to_concept(db_session, project, llm)
    project = project_service.advance_to_script(db_session, project, llm)
    project = project_service.advance_to_storyboard(db_session, project, llm)
    return project.shots[0]


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c
