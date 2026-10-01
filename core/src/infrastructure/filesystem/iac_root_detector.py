# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import shutil
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import final, override
from urllib.parse import urlparse, urlunparse

from src.domains.interfaces.iac_root_detector_interface import IIacRootDetector
from src.infrastructure.exceptions import RepositoryUnreachable
from src.infrastructure.filesystem.git.git_utils import GitUtils
from src.shared.config import system_config
from src.shared.logger import logging

_EXCLUDED_SEGMENTS = {"modules", "examples", "example", ".terraform"}

_ROOT_MARKERS = {
    "main.tf",
    "provider.tf",
    "providers.tf",
    "backend.tf",
    "terraform.tf",
    "versions.tf",
}


def _find_roots(file_paths: list[str]) -> list[str]:
    """Apply the Terraform root-module heuristic to a flat file listing.

    Args:
        file_paths: File paths as returned by ``git ls-tree -r HEAD --name-only``.

    Returns:
        Sorted POSIX-style directory paths that qualify as Terraform roots.
    """

    # Step 1 — group filenames by parent directory.
    dir_files: dict[str, set[str]] = defaultdict(set)
    for path in file_paths:
        p = PurePosixPath(path)
        dir_files[str(p.parent)].add(p.name)

    # Step 2 — candidate = any directory with at least one *.tf file.
    candidates = {
        d for d, names in dir_files.items() if any(n.endswith(".tf") for n in names)
    }

    # Step 3 — exclude directories whose path contains a banned segment.
    def _is_excluded(directory: str) -> bool:
        return bool(set(PurePosixPath(directory).parts) & _EXCLUDED_SEGMENTS)

    candidates = {d for d in candidates if not _is_excluded(d)}

    # Step 4 — keep only root-shaped candidates (two passes).
    def _has_tfvars(names: set[str]) -> bool:
        return any(n.endswith(".tfvars") or n.endswith(".tfvars.json") for n in names)

    def _has_root_marker(names: set[str]) -> bool:
        return bool(names & _ROOT_MARKERS)

    def _is_leaf(directory: str) -> bool:
        prefix = directory + "/"
        return not any(other.startswith(prefix) for other in candidates)

    def _is_under_existing_root(directory: str) -> bool:
        for root in marker_roots:
            if directory.startswith(root + "/"):
                return True
        return False

    # Pass 1: collect directories that qualify via markers or tfvars.
    marker_roots: set[str] = set()
    for d in candidates:
        names = dir_files[d]
        if _has_tfvars(names) or _has_root_marker(names):
            marker_roots.add(d)

    # Pass 2: add leaves that aren't nested under an existing root.
    roots: list[str] = list(marker_roots)
    for d in candidates:
        if d not in marker_roots and _is_leaf(d) and not _is_under_existing_root(d):
            roots.append(d)

    # Step 5 — return sorted.
    return sorted(roots)


@final
class IacRootDetector(IIacRootDetector):
    """Detects Terraform root modules by inspecting the git tree metadata."""

    @override
    async def detect_roots(self, repo_uri: str) -> list[str]:
        clone_dir = Path(tempfile.mkdtemp(prefix="iac-root-"))
        try:
            git = GitUtils(
                uri=repo_uri,
                git_provider=system_config.git.provider,
                cwd=clone_dir,
            )
            ok = await git.clone_repository(
                repo_uri,
                "repo",
                "--filter=blob:none",
                "--no-checkout",
                timeout=60,
            )
            if not ok:
                raise RepositoryUnreachable(502)

            repo_path = clone_dir / "repo"
            file_paths = await git.ls_tree(cwd=repo_path)
            roots = _find_roots(file_paths)

            parsed = urlparse(repo_uri)
            safe_uri = urlunparse(parsed._replace(netloc=parsed.hostname or ""))
            logging.info(
                "Scanned %s — found %d root(s)",
                safe_uri,
                len(roots),
            )
            return roots
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)
