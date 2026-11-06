from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.storage.models import DataSource

router = APIRouter()


@router.get("/sources", summary="Registered data sources and their documented provenance")
def list_sources(session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(DataSource).order_by(DataSource.name)).all()
    return {
        "count": len(rows),
        "sources": [
            {"id": r.id, "name": r.name, "source_type": r.source_type, "url": r.url,
             "permitted_usage": r.permitted_usage, "update_frequency": r.update_frequency,
             "historical_coverage": r.historical_coverage, "file_format": r.file_format,
             "last_successful_import": r.last_successful_import,
             "reliability_status": r.reliability_status}
            for r in rows
        ],
        "warnings": ["Historical coverage values are documentation only unless marked verified."],
    }
