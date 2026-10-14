"""Per-user connection to the Tut Agent runtime."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from open_notebook.tut import client

router = APIRouter(prefix="/tut", tags=["tut"])


class Connection(BaseModel):
    key: str


@router.get("/connection")
async def connection_status():
    return {"connected": await client.connected()}


@router.put("/connection")
async def connect(body: Connection):
    try:
        await client.save_key(body.key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {"connected": True}


@router.delete("/connection")
async def disconnect():
    await client.remove_key()
    return {"connected": False}
