from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import Subject
from db.schemas import CatalogueEntry, CatalogueResponse

router = APIRouter(prefix="/meta", tags=["metadata"])


@router.get("/catalogue", response_model=CatalogueResponse)
def get_catalogue(db: Session = Depends(get_db)):
    """Returns the (department, semester) pairs that actually have seeded academic data."""
    rows = (
        db.query(Subject.department, Subject.semester)
        .distinct()
        .order_by(Subject.department, Subject.semester)
        .all()
    )
    items = [CatalogueEntry(department=dept, semester=sem) for dept, sem in rows]
    return CatalogueResponse(items=items)

