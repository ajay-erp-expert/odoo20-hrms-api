from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from odoo_client import OdooClient, clean, get_odoo, m2o

router = APIRouter(prefix="/employees", tags=["Employee"])

MODEL = "hr.employee"
FIELDS = [
    "name", "work_email", "work_phone", "mobile_phone", "job_title",
    "department_id", "parent_id", "active",
]


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1)
    work_email: str | None = None
    work_phone: str | None = None
    mobile_phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    manager_id: int | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = None
    work_email: str | None = None
    work_phone: str | None = None
    mobile_phone: str | None = None
    job_title: str | None = None
    department_id: int | None = None
    manager_id: int | None = None


class EmployeeOut(BaseModel):
    id: int
    name: str
    work_email: str | None = None
    work_phone: str | None = None
    mobile_phone: str | None = None
    job_title: str | None = None
    department: dict | None = None
    manager: dict | None = None
    active: bool = True


def to_out(rec: dict) -> EmployeeOut:
    return EmployeeOut(
        id=rec["id"],
        name=rec["name"],
        work_email=clean(rec.get("work_email")),
        work_phone=clean(rec.get("work_phone")),
        mobile_phone=clean(rec.get("mobile_phone")),
        job_title=clean(rec.get("job_title")),
        department=m2o(rec.get("department_id")),
        manager=m2o(rec.get("parent_id")),
        active=rec.get("active", True),
    )


def to_vals(data: dict) -> dict:
    vals = dict(data)
    if "manager_id" in vals:
        vals["parent_id"] = vals.pop("manager_id")
    return vals


@router.get("", response_model=list[EmployeeOut])
async def list_employees(
    search: str | None = Query(None, description="Match on employee name"),
    include_archived: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    odoo: OdooClient = Depends(get_odoo),
):
    domain: list = []
    if search:
        domain.append(("name", "ilike", search))
    if include_archived:
        domain.append(("active", "in", [True, False]))
    records = await odoo.search_read(
        MODEL, domain, FIELDS, limit=limit, offset=offset, order="name asc"
    )
    return [to_out(r) for r in records]


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(employee_id: int, odoo: OdooClient = Depends(get_odoo)):
    records = await odoo.search_read(
        MODEL, [("id", "=", employee_id), ("active", "in", [True, False])], FIELDS, limit=1
    )
    if not records:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return to_out(records[0])


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(body: EmployeeCreate, odoo: OdooClient = Depends(get_odoo)):
    vals = to_vals(body.model_dump(exclude_none=True))
    new_id = await odoo.create(MODEL, vals)
    return await get_employee(new_id, odoo)


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: int, body: EmployeeUpdate, odoo: OdooClient = Depends(get_odoo)
):
    vals = to_vals(body.model_dump(exclude_unset=True))
    if not vals:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    await get_employee(employee_id, odoo)  # 404 if missing
    await odoo.write(MODEL, [employee_id], vals)
    return await get_employee(employee_id, odoo)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_employee(employee_id: int, odoo: OdooClient = Depends(get_odoo)):
    """Archives the employee (Odoo best practice) instead of deleting the record."""
    await get_employee(employee_id, odoo)
    await odoo.write(MODEL, [employee_id], {"active": False})
