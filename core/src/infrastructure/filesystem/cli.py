# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import subprocess
from collections.abc import Mapping

from src.infrastructure.exceptions import CliError, CliTimeoutError
from src.shared.logger import logging
from src.shared.utils.decorators import execute_pool

# Module-level default for the cli working directory when none is passed.
# Was previously Config.APP_HOME_DIR; the value never varied between
# deployments, so a constant is sufficient.
# TODO: is this default really needed?
_DEFAULT_CWD = "/usr/src/app"


class Cli:
    """
    A general-purpose CLI wrapper for executing command line commands using subprocess.

    This class provides a clean interface for running shell commands with proper error
    handling, timeout support, and environment customization. It's designed to be a
    lightweight, reusable component for any subprocess-based command execution.
    """

    def __init__(self, cwd: str | None = None):
        """
        Initializes the Cli instance.

        Args:
            cwd (str | None): The working directory where commands will be executed.
                             If None, commands will run in the current working directory.
        """
        self.__cwd = cwd if cwd is not None else _DEFAULT_CWD

    def run(
        self,
        command: list[str],
        timeout: int = 300,
        environment: Mapping[str, str] | None = None,
        capture_output: bool = True,
        check: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        """
        Executes a CLI command using subprocess.

        Args:
            command (list[str]): The command to execute as a list of strings.
                                Example: ["ls", "-la", "/home"]
            timeout (int, optional): The timeout for the command in seconds.
                                    Defaults to 300 (5 minutes).
            environment (Mapping[str, str] | None): Custom environment variables
                                                   for the command. If None, inherits
                                                   from the current process environment.
            capture_output (bool, optional): Whether to capture stdout and stderr.
                                           Defaults to True.
            check (bool, optional): If True, raises CalledProcessError if the command
                                   returns a non-zero exit code. Defaults to False.

        Returns:
            subprocess.CompletedProcess[bytes]: The result of the command execution,
                                               including returncode, stdout, and stderr.

        Raises:
            CliTimeoutError: If the command execution exceeds the timeout.
            CliError: If an unexpected error occurs during command execution.
        """
        try:
            result = subprocess.run(
                args=command,
                cwd=self.__cwd,
                capture_output=capture_output,
                timeout=timeout,
                env=environment,
                check=check,
            )

            if result.returncode != 0:
                logging.warning(
                    f"Command returned non-zero exit code {result.returncode}: {' '.join(command)}"
                )
                if capture_output:
                    error_msg = self._safe_cli_output(result)
                    logging.warning(f"STDOUT: {error_msg}")

            return result

        except subprocess.TimeoutExpired:
            error_msg = (
                f"Command timed out after {timeout} seconds: {' '.join(command)}"
            )
            logging.error(error_msg)
            raise CliTimeoutError(
                message=error_msg,
                error_code=408,  # HTTP timeout status code
            )

        except subprocess.CalledProcessError as e:
            error_msg = (
                f"Command failed with exit code {e.returncode}: {' '.join(command)}"
            )
            logging.error(error_msg)
            logging.error(f"ERROR OUTPUT: {self._safe_cli_output(e)}")
            raise CliError(
                message=error_msg,
                error_code=500,
            )

        except Exception as e:
            error_output = self._safe_cli_output(e)
            error_msg = f"Unexpected error executing command: {' '.join(command)} - {error_output}"
            logging.error(error_msg)
            raise CliError(
                message=error_msg,
                error_code=500,
            )

    @property
    def cwd(self) -> str | None:
        """
        Returns the current working directory for command execution.

        Returns:
            str | None: The working directory path, or None if using current directory.
        """
        return self.__cwd

    def set_cwd(self, cwd: str) -> None:
        """
        Sets the working directory for future command executions.

        Args:
            cwd (str): The new working directory path.
        """
        self.__cwd = cwd

    @execute_pool
    def execute(
        self,
        command: list[str],
        timeout: int = 300,
        environment: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """
        Executes a CLI command asynchronously.

        Runs the command in a thread pool to avoid blocking the event loop.
        Subclasses override this method to add authentication or other
        command preprocessing.

        Args:
            command (list[str]): The command to execute as a list of strings.
            timeout (int, optional): The timeout in seconds. Defaults to 300.
            environment (Mapping[str, str] | None): Environment variables for
                                                   the command.

        Returns:
            subprocess.CompletedProcess[bytes]: The result of the command execution.
        """
        return self.run(
            command=command,
            timeout=timeout,
            environment=environment,
        )

    @staticmethod
    def _safe_cli_output(response) -> str:
        parts = []
        for field in (response.stderr, response.stdout):
            if field is None:
                continue
            if isinstance(field, bytes):
                parts.append(field.decode("utf-8", errors="replace"))
            else:
                parts.append(str(field))
        return "".join(parts)
