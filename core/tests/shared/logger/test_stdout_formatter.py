# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import logging
import unittest

from src.shared.logger._stdout_formatter import StdoutFormatter


class TestStdoutFormatter(unittest.TestCase):
    def test_keeps_messages_that_contain_a_percent_sign(self):
        # e.g. the guard's rejection line for `https://[fe80::1%25eth0]/x`
        record = logging.LogRecord(
            "t", logging.WARNING, __file__, 1, "Rejected repo_uri a%25b %s", None, None
        )
        out = StdoutFormatter().format(record)
        self.assertIn("Rejected repo_uri a%25b %s", out)
