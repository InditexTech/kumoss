# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import inspect
import unittest

from src.application.use_cases.terraform_crud_handler import TerraformCRUDHandler
from src.application.use_cases.terraform_drift_handler import TerraformDriftHandler
from src.application.use_cases.terraform_apply_handler import TerraformApplyHandler


class TestHandlerSignature(unittest.TestCase):
    def test_handle_signature_takes_q(self):
        sig = inspect.signature(TerraformCRUDHandler.handle)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self", "q"])


class TestDriftHandlerSignature(unittest.TestCase):
    def test_handle_signature(self):
        sig = inspect.signature(TerraformDriftHandler.handle)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self", "q", "is_partial"])


class TestApplyHandlerSignature(unittest.TestCase):
    def test_handle_signature(self):
        # Apply takes nothing: it executes the session's pinned plan,
        # with no query, no targets and no regeneration inputs.
        sig = inspect.signature(TerraformApplyHandler.handle)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self"])
