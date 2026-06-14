# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

from src.domains.entities.document import Document
from src.shared.utils.decorators import execute_pool
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


# TODO: this class is hanging
class DocumentLoader:
    def __init__(
        self,
        documents_path: str,
        file_extension: str,
    ) -> None:
        """
        This class is responsible for splitting the source folder into
        a list of strings with the content of each file.
        :param documents_path: The path to the root folder.
        :param file_extension: The file extension to be considered.
        """
        self.__path: str = documents_path
        self.__file_extension: str = file_extension

    def __get_contents(self, file: os.DirEntry) -> Document:
        if file.name.endswith(self.__file_extension):
            with open(f"{file.path}", "r", encoding="utf-8") as f:
                try:
                    content = (
                        f.readlines() if self.__file_extension == ".txt" else f.read()
                    )
                except UnicodeDecodeError:
                    raise ExceptionHandler(
                        error_code=500, message=f"Error reading file {file.name}"
                    )
                metadata = {
                    "file_name": file.name,
                    "length": len(content),
                }
                return Document(content=content, metadata=metadata)
        logging.warning(f"File {file.name} is ignored.")

    def __recursive_search(
        self, curr_path: str, exclude_dirs: tuple[str]
    ) -> list[Document]:
        documents = []
        for element in os.scandir(curr_path):
            if element.name in exclude_dirs:
                logging.warning(f"dir/file {element.name} ignored as context files.")
                continue
            if element.is_dir():
                documents.extend(self.__recursive_search(element.path, exclude_dirs))
            else:
                documents.append(self.__get_contents(element))
        return documents

    @execute_pool
    def __load_documents(self, exclude_dirs: tuple[str]) -> list[Document]:
        """
        Load documents from the source folder.
        :return: List of Document objects.
        """
        p = Path(self.__path)

        if not p.exists():
            raise FileNotFoundError(f"Directory not found: {self.__path}")

        if not p.is_dir():
            raise ValueError(f"Expected directory, got file: {self.__path}")

        return self.__recursive_search(self.__path, exclude_dirs)

    @staticmethod
    def __append_metadata(content: str, metadata: dict[str, str | int]) -> str:
        return (
            "<"
            + metadata.get("file_name")
            + ">\n"
            + content
            + "</"
            + metadata.get("file_name")
            + ">"
        )

    @staticmethod
    async def retrieve_context(
        path: str, file_extensions: tuple[str, ...], exclude_dirs: tuple[str, ...] = ()
    ) -> list[str]:
        loaders = [
            DocumentLoader(
                documents_path=path,
                file_extension=ext,
            )
            for ext in file_extensions
        ]
        documents = [await loader.__load_documents(exclude_dirs) for loader in loaders]
        copy_docs = sorted(
            documents[0],
            key=lambda page: page.metadata["length"] if page is not None else 0,
            reverse=True,
        )
        for doc in copy_docs:
            logging.debug(doc.metadata) if doc else ""
        return [
            DocumentLoader.__append_metadata(page.content, page.metadata)
            for document in documents
            for page in document
            if page is not None
        ]
