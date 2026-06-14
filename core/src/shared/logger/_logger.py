# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import logging
import sys

from ._stdout_formatter import StdoutFormatter

# Get fancylog
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Check if the logger already has handlers to avoid duplicate logs
if not logger.handlers:
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(StdoutFormatter())
    logger.addHandler(stdout_handler)

logger.propagate = False
