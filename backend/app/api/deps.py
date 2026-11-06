from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.storage.database import get_engine


def get_db_engine() -> Engine:
    return get_engine()


def get_session(engine: Engine = Depends(get_db_engine)) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
