# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import subprocess
from pathlib import Path
from typing import override

from src.domains.interfaces.filesystem_interface import IFileSystem
from src.infrastructure.exceptions import CustomFileNotFoundError, RipgrepError
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class FileSystemUtils(IFileSystem):
    """Tool-oriented filesystem implementation for individual file operations."""

    def __init__(self, root: Path, file_ext: list[str] | None = None):
        """Caller MUST pass the actual IaC root directory; no discovery is performed.

        :param root: Absolute path to the IaC root directory.
        :param file_ext: Allowed file extensions.
        """
        self.__file_ext = file_ext if file_ext else ["tf", "tfvars"]
        self.__project_root_path = Path(root)

    @property
    @override
    def project_root(self) -> Path:
        """Get the project root path"""
        return Path(self.__project_root_path)

    @override
    def write_file(self, target_file: str, content: str, is_safe: bool = True) -> None:
        """Write content to a single file.
        If the file doesn't exist, a new one is created.

        :param target_file: Target file path relative to project root
        :param content: Content to write
        :param is_safe: Flag that checks a valid file extension
        """
        file_path = self.__resolve_path(target_file)
        if is_safe:
            self.__validate_file_extension(file_path.name)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            logging.warning(
                f"The file {target_file} already exists, content will be overwritten."
            )
        else:
            logging.info(f"The file {target_file} does not exist, it will be created.")

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                _ = file.write(content)
        except Exception as e:
            logging.error(f"Error writing to file {target_file} - {str(e)}")
            raise ExceptionHandler(
                error_code=500,
                message=f"Error writing to file {target_file} - {str(e)}",
            )

        if not file_path.exists():
            raise ExceptionHandler(
                error_code=500,
                message=f"File {target_file} was not created successfully",
            )

        logging.info(f"Successfully wrote to file {target_file}")

    @override
    def replace_in_file(self, target_file: str, search_replace_blocks: str) -> None:
        """Replace content in a file using search/replace blocks
        :param target_file: Target file path relative to project root
        :param search_replace_blocks: Search/replace blocks in the expected format
        :returns: True if successful
        """
        file_path = self.__resolve_path(target_file)
        if not file_path.exists():
            raise ExceptionHandler(
                error_code=404, message=f"File {target_file} does not exist"
            )
        self.__validate_file_extension(file_path.name)
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
            modified_content = self.__process_search_replace_blocks(
                content, search_replace_blocks
            )

            with open(file_path, "w", encoding="utf-8") as file:
                _ = file.write(modified_content)

            logging.info(f"Successfully replaced content in file {target_file}")

        except Exception as e:
            logging.error(f"Error replacing content in file {target_file}: {str(e)}")
            raise ExceptionHandler(
                error_code=500,
                message=f"Failed to replace content in file {target_file}: {str(e)}",
            )

    @override
    def delete_file(self, target_file: str) -> None:
        """Delete a single file
        :param target_file: Target file path relative to project root
        :returns: True if successful
        """
        try:
            file_path = self.__resolve_path(target_file)
            file_path.unlink()
            logging.info(f"Successfully deleted file {target_file}")
        except Exception as e:
            logging.error(f"Error deleting file {target_file}: {str(e)}")
            raise ExceptionHandler(
                error_code=500, message=f"Failed to delete file {target_file}: {str(e)}"
            )

    @override
    def read_file(self, target_file: str) -> str:
        """Read content from a single file
        :param: target_file: Target file path relative to project root
        :returns: File content
        """
        try:
            file_path = self.__resolve_path(target_file)

            if not file_path.exists():
                raise CustomFileNotFoundError(
                    error_code=404, message=f"File {target_file} does not exist"
                )

            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()

            logging.info(f"Successfully read file {target_file}")
            return content

        except FileNotFoundError:
            raise CustomFileNotFoundError(
                error_code=404, message=f"File {target_file} does not exist"
            )
        except Exception as e:
            logging.error(f"Error reading file {target_file}: {str(e)}")
            raise ExceptionHandler(
                error_code=500, message=f"Failed to read file {target_file}: {str(e)},"
            )

    @override
    def list_directory(self, relative_path: str = ".") -> list[Path]:
        """List contents of a directory
        :param relative_path: Directory path relative to project root
        :returns: List of file/directory names
        """
        try:
            dir_path: Path = self.__resolve_path(relative_path)

            if not dir_path.exists():
                raise ExceptionHandler(
                    error_code=404,
                    message=f"Directory {dir_path.as_posix()} does not exist",
                )

            if not dir_path.is_dir():
                raise ExceptionHandler(
                    error_code=400,
                    message=f"Path {dir_path.as_posix()} is not a directory",
                )

            return [i for i in dir_path.iterdir()]

        except Exception as e:
            logging.error(f"Error listing directory {relative_path}: {str(e)}")
            raise ExceptionHandler(
                error_code=500,
                message=f"Failed to list directory {relative_path}: {str(e)}",
            )

    @override
    def search_files(
        self,
        query: str,
        include_pattern: str = None,
        exclude_pattern: str = None,
        case_sensitive: bool = False,
    ) -> list[str]:
        """Search for text patterns in files using ripgrep
        :param query: Regex pattern to search for
        :param include_pattern: Glob pattern for files to include
        :param exclude_pattern: Glob pattern for files to exclude
        :param case_sensitive: Whether search should be case-sensitive
        :returns: Search results
        """
        cmd = ["rg", "--line-number", "--with-filename"]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if include_pattern:
            cmd.extend(["--glob", include_pattern])
        if exclude_pattern:
            cmd.extend(["--glob", f"!{exclude_pattern}"])
        cmd.extend(["--max-count", "50"])  # Limit results
        cmd.append(query)
        cmd.append(str(self.project_root))

        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root
        )

        if result.returncode == 0:
            return result.stdout.strip().split("\n") if result.stdout.strip() else []
        elif result.returncode == 1:  # no matches found
            return [f"No matches found for {query}"]
        logging.error(f"Ripgrep error: {result.stderr}")
        raise RipgrepError(
            message=result.stderr,
            error_code=result.returncode,
        )

    def __file_exists(self, target_file: str) -> bool:
        """Check if a file exists
        :param target_file: Target file path relative to project root
        :returns: True if file exists
        """
        file_path = self.__resolve_path(target_file)
        return file_path.exists() and file_path.is_file()

    def __validate_file_extension(self, file_name: str) -> None:
        """Validate file extension against allowed extensions
        :param file_name: Name of the file to validate
        """
        if not self.__file_ext:
            return

        file_ext = file_name.split(".")[-1] if "." in file_name else ""
        if file_ext not in self.__file_ext:
            raise ExceptionHandler(
                message=f"File extension violation. File '{file_name}' cannot be modified. "
                + f"Allowed extensions: {self.__file_ext}",
                error_code=400,
            )

    def __resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute path within the project root
        :param relative_path: Path relative to project root
        :returns: Absolute path
        """
        return self.project_root / relative_path

    def __process_search_replace_blocks(self, content: str, blocks: str) -> str:
        """Process search/replace blocks in a specific format (refer to tool definition)
        :param content: previous file content
        """
        parts = blocks.split(">>>>>>> REPLACE")

        parse_blocks = [part.split("=======") for part in parts if part.strip()]

        for block in parse_blocks:
            search = block[0].replace("<<<<<<< SEARCH", "").strip()
            replace = block[1].strip()
            content = content.replace(search, replace, 1)

        return content
