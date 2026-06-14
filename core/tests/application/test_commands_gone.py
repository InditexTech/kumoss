# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import importlib
import unittest


class TestCommandsModuleGone(unittest.TestCase):
    def test_import_fails(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("src.application.commands")
