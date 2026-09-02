"""SQLAlchemy engine/session setup. SQLite for now; swapping to Postgres later
only means changing DATABASE_URL, nothing else in the app."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import ROOT_DIR, settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables if they don't exist yet. No migration framework in Milestone 1 -
    the schema is still moving fast; we'll add Alembic once it stabilizes."""
    if settings.database_url.startswith("sqlite:///./"):
        (ROOT_DIR / "data").mkdir(parents=True, exist_ok=True)
    import app.models.project  # noqa: F401  (ensures models are registered on Base)
    import app.models.video_job  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
