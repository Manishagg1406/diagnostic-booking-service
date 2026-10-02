from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.errors import ConflictError, NotFoundError
from app.db import get_db
from app.deps import require_admin
from app.models import Centre, CentreTest, DiagnosticTest
from app.schemas import (
    CentreCreate,
    CentreDetail,
    CentreOut,
    CentreTestCreate,
    CentreTestOut,
    TestCreate,
    TestOut,
)

router = APIRouter(tags=["catalog"])


def _centre_detail(centre: Centre) -> CentreDetail:
    return CentreDetail(
        id=centre.id,
        name=centre.name,
        location=centre.location,
        tests=[CentreTestOut(test_id=o.test_id, test_name=o.test.name, price=o.price) for o in centre.offerings],
    )


def _load_centre(db: Session, centre_id: int) -> Centre:
    centre = db.scalar(
        select(Centre)
        .where(Centre.id == centre_id)
        .options(selectinload(Centre.offerings).joinedload(CentreTest.test))
    )
    if centre is None:
        raise NotFoundError("Centre not found")
    return centre


# ----- diagnostic tests -----
@router.post("/tests", response_model=TestOut, status_code=201)
def create_test(data: TestCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    name = data.name.strip()
    if db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name)):
        raise ConflictError("A test with this name already exists")
    test = DiagnosticTest(name=name)
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("A test with this name already exists")
    return test


@router.get("/tests", response_model=list[TestOut])
def list_tests(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return db.scalars(select(DiagnosticTest).order_by(DiagnosticTest.id).limit(limit).offset(offset)).all()


# ----- centres -----
@router.post("/centres", response_model=CentreOut, status_code=201)
def create_centre(data: CentreCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    centre = Centre(name=data.name.strip(), location=data.location.strip())
    db.add(centre)
    db.commit()
    return centre


@router.get("/centres", response_model=list[CentreOut])
def list_centres(
    location: str | None = Query(None, description="Case-insensitive substring match"),
    test_id: int | None = Query(None, description="Only centres offering this test"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Centre).order_by(Centre.id)
    if location:
        stmt = stmt.where(Centre.location.ilike(f"%{location}%"))
    if test_id is not None:
        stmt = stmt.where(Centre.id.in_(select(CentreTest.centre_id).where(CentreTest.test_id == test_id)))
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.get("/centres/{centre_id}", response_model=CentreDetail)
def get_centre(centre_id: int, db: Session = Depends(get_db)):
    return _centre_detail(_load_centre(db, centre_id))


@router.post("/centres/{centre_id}/tests", response_model=CentreDetail, status_code=201)
def add_test_to_centre(
    centre_id: int, data: CentreTestCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)
):
    centre = _load_centre(db, centre_id)
    if db.get(DiagnosticTest, data.test_id) is None:
        raise NotFoundError("Test not found")
    db.add(CentreTest(centre_id=centre.id, test_id=data.test_id, price=data.price))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This centre already offers that test")
    db.expire_all()
    return _centre_detail(_load_centre(db, centre_id))
