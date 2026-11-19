"""Async client for Odoo's External JSON-2 API (POST /json/2/<model>/<method>).

Odoo 20 removed XML-RPC / JSON-RPC, so JSON-2 with an API key is the supported way in.
Every call runs with the permissions of the user that owns the API key.
"""
from typing import Any

import httpx
from fastapi import Request

from config import Settings


class OdooError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class OdooClient:
    def __init__(self, settings: Settings):
        self._http = httpx.AsyncClient(
            base_url=settings.odoo_url.rstrip("/"),
            timeout=settings.odoo_timeout,
            headers={
                "Authorization": f"bearer {settings.odoo_api_key}",
                "X-Odoo-Database": settings.odoo_db,
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(
        self,
        model: str,
        method: str,
        ids: list[int] | None = None,
        **kwargs: Any,
    ) -> Any:
        payload: dict[str, Any] = dict(kwargs)
        if ids is not None:
            payload["ids"] = ids
        try:
            resp = await self._http.post(f"/json/2/{model}/{method}", json=payload)
        except httpx.RequestError as exc:
            raise OdooError(503, f"Cannot reach Odoo: {exc}") from exc

        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("message") or body.get("name") or resp.text
            except ValueError:
                message = resp.text
            raise OdooError(resp.status_code, message)
        return resp.json()

    # ---- thin ORM helpers -------------------------------------------------
    async def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict]:
        return await self.call(
            model,
            "search_read",
            domain=domain or [],
            fields=fields or [],
            limit=limit,
            offset=offset,
            order=order,
        )

    async def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict]:
        return await self.call(model, "read", ids=ids, fields=fields)

    async def create(self, model: str, vals: dict) -> int:
        result = await self.call(model, "create", vals_list=[vals])
        return result[0] if isinstance(result, list) else result

    async def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return await self.call(model, "write", ids=ids, vals=vals)

    async def unlink(self, model: str, ids: list[int]) -> bool:
        return await self.call(model, "unlink", ids=ids)


def get_odoo(request: Request) -> OdooClient:
    """FastAPI dependency returning the shared client created at startup."""
    return request.app.state.odoo


def m2o(value: Any) -> dict | None:
    """Odoo many2one -> {"id": .., "name": ..} (or None when empty)."""
    if not value:
        return None
    return {"id": value[0], "name": value[1]}


def clean(value: Any) -> Any:
    """Odoo returns False for empty values; map that to None."""
    return None if value is False else value
