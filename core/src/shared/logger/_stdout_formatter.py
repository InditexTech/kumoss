# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import logging

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
LIGHTBLACK_EX = "\033[90m"
LIGHTRED_EX = "\033[91m"
LIGHTGREEN_EX = "\033[92m"
LIGHTYELLOW_EX = "\033[93m"
LIGHTBLUE_EX = "\033[94m"
LIGHTMAGENTA_EX = "\033[95m"
LIGHTCYAN_EX = "\033[96m"
RESET = "\033[0m"


class StdoutFormatter(logging.Formatter):
    """
    Logger formatter.
    """

    def format(self, record):
        """
        Formats a log record with color-coded output based on the log level.

        Args:
            record: The log record to format.

        Returns:
            The formatted log record as a string.
        """
        level = "%(levelname)s"
        module_name = getattr(record, "module_name", "%(module)s").lower()
        module = f"{LIGHTCYAN_EX}[{module_name}]"
        date_format = getattr(record, "date_format", "%H:%M:%S")
        date = f"{LIGHTBLACK_EX}[%(asctime)s] "
        # Spliced into a %-style format string below.
        msg = f"{RESET}{record.getMessage().replace('%', '%%')}"
        formats = {
            logging.DEBUG: f"{LIGHTMAGENTA_EX}{level}:{module}{date}{msg}",
            logging.INFO: f"{LIGHTGREEN_EX}{level}:{module}{date}{msg}",
            logging.WARNING: f"{LIGHTYELLOW_EX}{level}:{module}{date}{msg}",
            logging.ERROR: f"{LIGHTRED_EX}{level}:{module}{date}{msg}",
            logging.CRITICAL: f"{RED}{level}:{module}{date}{msg}",
        }
        formatter = logging.Formatter(
            fmt=formats.get(record.levelno), datefmt=date_format
        )
        return formatter.format(record)
