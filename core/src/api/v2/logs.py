# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated

from fastapi import APIRouter, HTTPException, UploadFile, File

from src.domains.dto import TerraformPlanParseDTO
from src.shared.exceptions import ExceptionHandler
from src.infrastructure.utils.terraform_plan_parser import TerraformPlanParser

router = APIRouter(
    prefix="/logs",
    tags=["Logs & Metrics"],
)


@router.post(
    path="/terraform/parser",
    summary="Perform a drift detection on the given terraform Plan",
)
async def terraform_parser(
    terraform_plan: Annotated[
        UploadFile,
        File(description="The terrafom plan in plain text format"),
    ],
) -> TerraformPlanParseDTO:
    if terraform_plan.content_type != "text/plain":
        raise HTTPException(
            status_code=400,
            detail="Content type must be 'text/plain'",
        )
    content = await terraform_plan.read()
    try:
        return TerraformPlanParser(content.decode()).filter_duplicates()
    except ExceptionHandler as e:
        raise HTTPException(
            status_code=e.error_code,
            detail=e.message,
        )
