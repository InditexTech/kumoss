# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


class Document:
    def __init__(self, content: str, metadata: dict[str, str]) -> None:
        """
        Class for storing a piece of text and associated metadata.
        :param content: String text.
        :param metadata: Arbitrary metadata about the page content (e.g., source, relationships to other documents, etc.).
        """
        self.content: str = content
        self.metadata: dict[str, str] = metadata

    def __str__(self) -> str:
        return self.content
