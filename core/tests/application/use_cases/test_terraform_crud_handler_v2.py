# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import inspect
import unittest

from src.application.use_cases.terraform_crud_handler import TerraformCRUDHandler
from src.application.use_cases.terraform_drift_handler import TerraformDriftHandler
from src.application.use_cases.terraform_apply_handler import TerraformApplyHandler


class TestHandlerSignature(unittest.TestCase):
    def test_handle_signature_takes_q_and_history(self):
        sig = inspect.signature(TerraformCRUDHandler.handle)
        params = list(sig.parameters.keys())
        # self, q, history
        self.assertEqual(params, ["self", "q", "history"])


class TestDriftHandlerSignature(unittest.TestCase):
    def test_handle_signature(self):
        sig = inspect.signature(TerraformDriftHandler.handle)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self", "q", "history", "is_partial"])


class TestApplyHandlerSignature(unittest.TestCase):
    def test_handle_signature(self):
        sig = inspect.signature(TerraformApplyHandler.handle)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["self", "q", "terraform_targets"])
