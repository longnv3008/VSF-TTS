from __future__ import annotations

from fastapi import APIRouter

# Router health dùng để kiểm tra app còn sống hay không.
router = APIRouter()


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
