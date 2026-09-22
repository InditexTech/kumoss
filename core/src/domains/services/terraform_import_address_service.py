# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import re

from src.domains.interfaces import IFileSystem
from src.domains.interfaces.git_interface import IGit
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

_BLOCK = re.compile(r'^resource\s+"(?P<type>[^"]+)"\s+"(?P<label>[^"]+)"')
_NAME = re.compile(r'^\s*name\s*=\s*"(?P<name>[^"]+)"')


class TerraformImportAddressService:
    """Pairs the resource blocks an import round generated with their ids.

    The generation round writes the blocks into the root module; this
    service reads them back from the session branch diff and returns the
    `terraform import <address> <resource_id>` arguments for each one.

    The pairing needs no inference. A block never carries its own cloud
    resource id, but the generator derives its `name` from the id it was
    asked to import, and that name is the id's last path segment. So the
    round's selected ids drive the lookup and the diff only has to say
    which block each of them landed in.

    An id that does not resolve to exactly one added block is left out,
    never guessed: a missed import reappears downstream as drift, whereas
    a wrong address corrupts the Terraform state.
    """

    def __init__(
        self,
        git: IGit,
        files: IFileSystem,
    ):
        self.__git = git
        self.__files = files

    async def get_import_addresses(
        self, selected_ids: list[str]
    ) -> list[tuple[str, str]]:

        logging.debug(f"Selected ids: {selected_ids}")
        blocks = self.__added_blocks(await self.__added_lines())
        imports: list[tuple[str, str]] = []

        logging.debug(f"Added blocks: {blocks}")

        for resource_id in selected_ids:
            name = re.split(r"[/:]", resource_id)[-1]
            matches = [addr for addr, block in blocks.items() if block == name]
            if len(matches) != 1:
                logging.warning(
                    f"No single generated block matches {resource_id}: {matches}"
                )
                continue
            imports.append((matches[0], resource_id))
            logging.debug(f"Matched block for {resource_id}: {matches[0]}")
            del blocks[matches[0]]
        return imports

    async def __added_lines(self) -> list[str]:
        """Collect the Terraform the session branch added.

        Only added diff lines count: a context line is code that already
        existed, and a block that already existed is not for this round to
        import. Untracked files are new in full.
        """
        lines: list[str] = []
        target = ""
        for line in (
            await self.__git.show_diff(working_tree=False, full_content=False)
        ).splitlines():
            if line.startswith("+++ "):
                target = line.removeprefix("+++ ")
            elif line.startswith("+") and target.endswith(".tf"):
                lines.append(line[1:])

        for file in await self.__git.get_untracked_files():
            if not file.endswith(".tf"):
                continue
            try:
                lines.extend(self.__files.read_file(file).splitlines())
            except ExceptionHandler as e:
                logging.warning(f"Error reading file '{file}': {e.message}")
        return lines

    def __added_blocks(self, lines: list[str]) -> dict[str, str]:
        """Map the address of every added resource block to its cloud name.

        Anchoring the block at column zero keeps the root module resources
        and leaves out both nested blocks and the `variable`, `locals`,
        `output`, `provider`, `terraform` and `data` ones.
        """
        blocks: dict[str, str] = {}
        address = ""
        for line in lines:
            if block := _BLOCK.match(line):
                address = f"{block['type']}.{block['label']}"
                blocks[address] = block["label"]
            elif address and (name := _NAME.match(line)):
                blocks[address] = name["name"]
                address = ""
        return blocks
