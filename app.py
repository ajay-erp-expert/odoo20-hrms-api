from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from attendance.apply_attendance import router as attendance_router
from config import settings
from employee.employee_creation import router as employee_router
from leave.apply_leave import router as leave_router
from odoo_client import OdooClient, OdooError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.odoo = OdooClient(settings)
    yield
    await app.state.odoo.aclose()


app = FastAPI(title="Odoo 20 HR API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(OdooError)
async def odoo_error_handler(_: Request, exc: OdooError):
    # Pass through client-side errors from Odoo (auth, access, validation); hide the rest as 502
    status_code = exc.status_code if exc.status_code in (400, 401, 403, 404, 409, 422) else (
        503 if exc.status_code == 503 else 502
    )
    return JSONResponse(status_code=status_code, content={"detail": exc.message})


@app.get("/hello_world", tags=["Health"])
async def root():
    return {"message": "Hello World"}


@app.get("/health/odoo", tags=["Health"])
async def odoo_health(request: Request):
    """Verifies URL, database name and API key against the Odoo 20 server."""
    count = await request.app.state.odoo.call("hr.employee", "search_count", domain=[])
    return {"status": "ok", "database": settings.odoo_db, "employees": count}


app.include_router(employee_router)
app.include_router(attendance_router)
app.include_router(leave_router)
