from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from odoo_client import OdooClient, clean, get_odoo, m2o

router = APIRouter(prefix="/attendance", tags=["Attendance"])

MODEL = "hr.attendance"
FIELDS = ["employee_id", "check_in", "check_out", "worked_hours", "state"]


class CheckIn(BaseModel):
    employee_id: int
    check_in: datetime | None = None  # defaults to now; naive values are treated as UTC


class CheckOut(BaseModel):
    employee_id: int
    check_out: datetime | None = None


class AttendanceOut(BaseModel):
    id: int
    employee: dict | None = None
    check_in: str | None = None  # UTC, as stored by Odoo
    check_out: str | None = None
    worked_hours: float = 0.0
    state: str | None = None


def odoo_dt(value: datetime | None) -> str:
    """Odoo stores datetimes as naive UTC strings."""
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def to_out(rec: dict) -> AttendanceOut:
    return AttendanceOut(
        id=rec["id"],
        employee=m2o(rec.get("employee_id")),
        check_in=clean(rec.get("check_in")),
        check_out=clean(rec.get("check_out")),
        worked_hours=rec.get("worked_hours") or 0.0,
        state=clean(rec.get("state")),
    )


async def _open_attendance(odoo: OdooClient, employee_id: int) -> dict | None:
    rows = await odoo.search_read(
        MODEL,
        [("employee_id", "=", employee_id), ("check_out", "=", False)],
        FIELDS,
        limit=1,
        order="check_in desc",
    )
    return rows[0] if rows else None


@router.post("/check-in", response_model=AttendanceOut, status_code=status.HTTP_201_CREATED)
async def check_in(body: CheckIn, odoo: OdooClient = Depends(get_odoo)):
    if await _open_attendance(odoo, body.employee_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee is already checked in")
    new_id = await odoo.create(
        MODEL, {"employee_id": body.employee_id, "check_in": odoo_dt(body.check_in)}
    )
    return to_out((await odoo.read(MODEL, [new_id], FIELDS))[0])


@router.post("/check-out", response_model=AttendanceOut)
async def check_out(body: CheckOut, odoo: OdooClient = Depends(get_odoo)):
    open_rec = await _open_attendance(odoo, body.employee_id)
    if not open_rec:
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee is not checked in")
    await odoo.write(MODEL, [open_rec["id"]], {"check_out": odoo_dt(body.check_out)})
    return to_out((await odoo.read(MODEL, [open_rec["id"]], FIELDS))[0])


@router.get("", response_model=list[AttendanceOut])
async def list_attendance(
    employee_id: int | None = None,
    date_from: date | None = Query(None, description="check_in on/after (UTC date)"),
    date_to: date | None = Query(None, description="check_in on/before (UTC date)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    odoo: OdooClient = Depends(get_odoo),
):
    domain: list = []
    if employee_id:
        domain.append(("employee_id", "=", employee_id))
    if date_from:
        domain.append(("check_in", ">=", f"{date_from} 00:00:00"))
    if date_to:
        domain.append(("check_in", "<=", f"{date_to} 23:59:59"))
    rows = await odoo.search_read(
        MODEL, domain, FIELDS, limit=limit, offset=offset, order="check_in desc"
    )
    return [to_out(r) for r in rows]


@router.get("/{attendance_id}", response_model=AttendanceOut)
async def get_attendance(attendance_id: int, odoo: OdooClient = Depends(get_odoo)):
    rows = await odoo.search_read(MODEL, [("id", "=", attendance_id)], FIELDS, limit=1)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance not found")
    return to_out(rows[0])
