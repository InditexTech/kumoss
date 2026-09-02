# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from pathlib import Path


class IFileSystem(ABC):
    """Tool-oriented filesystem interface for individual file operations"""

    @property
    @abstractmethod
    def project_root(self) -> Path:
        """Get the project root path"""
        pass

    @abstractmethod
    def write_file(self, target_file: str, content: str, is_safe: bool = True) -> bool:
        """
        Write content to a single file.
        If the file doesn't exist, a new one is created.

        Args:
            target_file: Target file path relative to project root
            content: Content to write
            is_safe: flag that checks a valid file extension

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def replace_in_file(self, target_file: str, search_replace_blocks: str) -> bool:
        """
        Replace content in a file using search/replace blocks

        Args:
            target_file: Target file path relative to project root
            search_replace_blocks: Search/replace blocks in the expected format

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def delete_file(self, target_file: str) -> bool:
        """
        Delete a single file

        Args:
            target_file: Target file path relative to project root

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def read_file(self, target_file: str) -> str:
        """
        Read content from a single file

        Args:
            target_file: Target file path relative to project root

        Returns:
            File content
        """
        pass

    @abstractmethod
    def list_directory(self, relative_path: str = ".") -> list[str]:
        """
        List contents of a directory

        Args:
            relative_path: Directory path relative to project root

        Returns:
            List of file/directory names
        """
        pass

    @abstractmethod
    def search_files(
        self,
        query: str,
        include_pattern: str = None,
        exclude_pattern: str = None,
        case_sensitive: bool = False,
    ) -> list[str]:
        """
        Search for text patterns in files

        Args:
            query: Regex pattern to search for
            include_pattern: Glob pattern for files to include
            exclude_pattern: Glob pattern for files to exclude
            case_sensitive: Whether search should be case-sensitive

        Returns:
            Search results
        """
        pass
