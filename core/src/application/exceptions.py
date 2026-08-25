# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from src.shared.exceptions import ExceptionHandler


class ReportGenerationError(ExceptionHandler):
    """Report generation inference error"""

    pass


class TerraformValidationFailedError(ExceptionHandler):
    """Raised when Terraform validation loop has been exhausted and failed"""

    pass


class SetLockError(ExceptionHandler):
    """Raised when the DB lock update encountered an error"""

    pass
