from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator

from odoo_client import OdooClient, clean, get_odoo, m2o

router = APIRouter(prefix="/leaves", tags=["Leave"])

MODEL = "hr.leave"
# In Odoo 20 the leave type is an hr.work.entry.type (no more hr.leave.type)
TYPE_MODEL = "hr.work.entry.type"
FIELDS = [
    "employee_id", "work_entry_type_id", "request_date_from", "request_date_to",
    "date_from", "date_to", "number_of_days", "state", "name", "notes",
]


class LeaveApply(BaseModel):
    employee_id: int
    work_entry_type_id: int
    date_from: date
    date_to: date
    reason: str | None = None
    # only meaningful for leave types that allow half days
    date_from_period: Literal["am", "pm"] | None = None
    date_to_period: Literal["am", "pm"] | None = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        return self


class LeaveOut(BaseModel):
    id: int
    employee: dict | None = None
    leave_type: dict | None = None
    date_from: str | None = None
    date_to: str | None = None
    number_of_days: float = 0.0
    state: str | None = None
    description: str | None = None
    reason: str | None = None


class LeaveTypeOut(BaseModel):
    id: int
    name: str
    code: str | None = None
    requires_allocation: bool | None = None
    validation: str | None = None


def to_out(rec: dict) -> LeaveOut:
    return LeaveOut(
        id=rec["id"],
        employee=m2o(rec.get("employee_id")),
        leave_type=m2o(rec.get("work_entry_type_id")),
        date_from=clean(rec.get("request_date_from")),
        date_to=clean(rec.get("request_date_to")),
        number_of_days=rec.get("number_of_days") or 0.0,
        state=clean(rec.get("state")),
        description=clean(rec.get("name")),
        reason=clean(rec.get("notes")),
    )


async def _get(odoo: OdooClient, leave_id: int) -> dict:
    rows = await odoo.search_read(MODEL, [("id", "=", leave_id)], FIELDS, limit=1)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")
    return rows[0]


@router.get("/types", response_model=list[LeaveTypeOut])
async def list_leave_types(odoo: OdooClient = Depends(get_odoo)):
    rows = await odoo.search_read(
        TYPE_MODEL,
        [("time_off_selectable", "=", True)],
        ["name", "code", "requires_allocation", "leave_validation_type"],
        order="sequence",
    )
    return [
        LeaveTypeOut(
            id=r["id"],
            name=r["name"],
            code=clean(r.get("code")),
            requires_allocation=r.get("requires_allocation"),
            validation=clean(r.get("leave_validation_type")),
        )
        for r in rows
    ]


@router.get("", response_model=list[LeaveOut])
async def list_leaves(
    employee_id: int | None = None,
    state: Literal["confirm", "validate1", "validate", "refuse", "cancel"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    odoo: OdooClient = Depends(get_odoo),
):
    domain: list = []
    if employee_id:
        domain.append(("employee_id", "=", employee_id))
    if state:
        domain.append(("state", "=", state))
    if date_from:
        domain.append(("request_date_to", ">=", str(date_from)))
    if date_to:
        domain.append(("request_date_from", "<=", str(date_to)))
    rows = await odoo.search_read(
        MODEL, domain, FIELDS, limit=limit, offset=offset, order="date_from desc"
    )
    return [to_out(r) for r in rows]


@router.get("/{leave_id}", response_model=LeaveOut)
async def get_leave(leave_id: int, odoo: OdooClient = Depends(get_odoo)):
    return to_out(await _get(odoo, leave_id))


@router.post("", response_model=LeaveOut, status_code=status.HTTP_201_CREATED)
async def apply_leave(body: LeaveApply, odoo: OdooClient = Depends(get_odoo)):
    vals: dict = {
        "employee_id": body.employee_id,
        "work_entry_type_id": body.work_entry_type_id,
        "request_date_from": str(body.date_from),
        "request_date_to": str(body.date_to),
    }
    if body.reason:
        vals["name"] = body.reason
    if body.date_from_period:
        vals["request_date_from_period"] = body.date_from_period
    if body.date_to_period:
        vals["request_date_to_period"] = body.date_to_period
    new_id = await odoo.create(MODEL, vals)
    return to_out(await _get(odoo, new_id))


@router.post("/{leave_id}/approve", response_model=LeaveOut)
async def approve_leave(leave_id: int, odoo: OdooClient = Depends(get_odoo)):
    await _get(odoo, leave_id)
    await odoo.call(MODEL, "action_approve", ids=[leave_id])
    return to_out(await _get(odoo, leave_id))


@router.post("/{leave_id}/refuse", response_model=LeaveOut)
async def refuse_leave(leave_id: int, odoo: OdooClient = Depends(get_odoo)):
    await _get(odoo, leave_id)
    await odoo.call(MODEL, "action_refuse", ids=[leave_id])
    return to_out(await _get(odoo, leave_id))
