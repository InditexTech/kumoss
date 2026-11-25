# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from .conventions import Conventions
from .manifest import (
    Manifest,
    RootModuleRef,
    TerraformInputs,
    Variable,
    VariableAnswer,
)
from .manifest_resolution import ManifestResolution, ProviderChange
from .page_summary import PageSummary
from .plan_ref import PlanRef
from .provider_scope import ProviderScope
from .search_result import SearchResult
from .status import Status
from .terraform_doc import TerraformDoc
from .terraform_requirements import (
    ProviderRequirement,
    TerraformRequirements,
    VarFile,
    VariableSpec,
)
from .token_claims import TokenClaims
from .workspace_facts import WorkspaceFacts

__all__ = [
    "Conventions",
    "Manifest",
    "ManifestResolution",
    "PageSummary",
    "PlanRef",
    "ProviderChange",
    "ProviderRequirement",
    "ProviderScope",
    "RootModuleRef",
    "SearchResult",
    "Status",
    "TerraformDoc",
    "TerraformInputs",
    "TerraformRequirements",
    "TokenClaims",
    "VarFile",
    "Variable",
    "VariableAnswer",
    "VariableSpec",
    "WorkspaceFacts",
]
