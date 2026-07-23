# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import final

from src.infrastructure.templates._common import CommonTemplateAdapter


@final
class OCITemplateAdapter(CommonTemplateAdapter):
    _scope = "oci"
