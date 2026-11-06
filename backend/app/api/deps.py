from sqlalchemy import Engine

from app.storage.database import get_engine


def get_db_engine() -> Engine:
    return get_engine()
