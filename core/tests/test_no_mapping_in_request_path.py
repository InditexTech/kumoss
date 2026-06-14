# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import subprocess
import unittest
from pathlib import Path


class TestMappingNotImported(unittest.TestCase):
    def test_no_mapping_resolver_in_handlers_or_endpoints(self):
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "grep",
                "-RIn",
                "-e",
                "from src.clients.mapping_resolver",
                "-e",
                "import resolve_mapping",
                "core/src/api/",
                "core/src/application/use_cases/",
                "core/src/application/factory.py",
            ],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        self.assertEqual(
            result.returncode,
            1,  # 1 == grep found nothing
            "resolve_mapping still wired in core request path:\n"
            f"{result.stdout}{result.stderr}",
        )
