from fastapi import APIRouter, Depends, Response
from sqlalchemy import Engine

from app import __version__
from app.api.deps import get_db_engine
from app.monitoring.health import check_database

router = APIRouter()


@router.get("/health", summary="DataCore service and database status")
def health(response: Response, engine: Engine = Depends(get_db_engine)) -> dict:
    db = check_database(engine)
    healthy = db["connected"] and db["expected_tables_present"]
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "service": "atlas-datacore",
            "version": __version__, "database": db}
