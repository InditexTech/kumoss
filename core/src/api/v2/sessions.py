# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.domains.services.database_service import DatabaseService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    repo_uri: str
    cloud_provider: str
    environment: str
    branch_name: str
    status: str
    in_flight: bool
    created_at: datetime
    updated_at: datetime


@router.get("/", summary="List sessions")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(
        None, description="Search by user_id or repo_uri (partial match)"
    ),
    status: Optional[str] = Query(None),
) -> dict:
    offset = (page - 1) * page_size
    items, total = await DatabaseService.list_sessions(
        search=search,
        status=status,
        offset=offset,
        limit=page_size,
    )
    return {
        "items": [
            SessionResponse.model_validate(s, from_attributes=True).model_dump()
            for s in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{session_id}", summary="Get session detail")
async def get_session(session_id: str) -> SessionResponse:
    session = await DatabaseService.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return SessionResponse.model_validate(session, from_attributes=True)
