# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.deps import CurrentUser, get_current_user
from src.api.dtos import UserMeResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    path="/me",
    summary="The authenticated caller's identity and roles.",
)
async def users_me(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> UserMeResponse:
    return UserMeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        operation_role=user.operation_role,
        panel_role=user.panel_role,
    )
