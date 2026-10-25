from sqlalchemy.orm import Session
from ..db import get_session, SessionLocal  # noqa: F401
from ..settings import Settings


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def get_settings() -> Settings:
    return Settings()
