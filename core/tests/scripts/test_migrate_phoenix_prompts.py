# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The Phoenix to Langfuse prompt migration script (core/scripts/)."""

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any


def _load() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2] / "scripts" / "migrate_phoenix_prompts.py"
    )
    spec = importlib.util.spec_from_file_location("migrate_phoenix_prompts", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = _load()


def _version(id: str, tags: list[str], text: str | None = "t") -> dict[str, Any]:
    return {"id": id, "tags": tags, "text": text, "description": None}


class _Langfuse:
    """Answers GET v2/prompts/<name> by label or version number."""

    def __init__(self, versions: dict[int, tuple[int, dict[str, Any] | None]]):
        self.versions = versions

    def call(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ):
        params = params or {}
        if params.get("label") == "latest":
            return 200, {"version": max(self.versions)}
        return self.versions[params["version"]]


class TestNames(unittest.TestCase):
    def test_kumoss_prompts_move_into_their_folders(self):
        self.assertEqual(
            m.langfuse_name("aws-guidelines-networking"), "aws/guidelines/networking"
        )
        self.assertEqual(
            m.langfuse_name("my-scope-resources-x_y"), "my-scope/resources/x_y"
        )

    def test_other_prompts_keep_their_name(self):
        self.assertEqual(m.langfuse_name("random-prompt"), "random-prompt")


class TestLabels(unittest.TestCase):
    def test_a_tag_longer_than_a_langfuse_label_is_not_a_label(self):
        self.assertTrue(m._LABEL_RE.match("a" * 36))
        self.assertFalse(m._LABEL_RE.match("a" * 37))


class TestSeedFallback(unittest.TestCase):
    def test_without_a_seed_tag_the_oldest_readable_version_gets_it(self):
        versions = [
            _version("v1", ["staging"], text=None),
            _version("v2", ["development"]),
            _version("v3", ["production"]),
        ]

        m._seed_fallback("p", versions)

        # The operator's latest version is left alone: the seeder would
        # otherwise take it as its own and move its labels.
        self.assertEqual(
            [v["tags"] for v in versions],
            [["staging"], ["development", "seed"], ["production"]],
        )

    def test_an_existing_seed_tag_is_kept_where_it_is(self):
        versions = [_version("v1", []), _version("v2", ["seed"])]

        m._seed_fallback("p", versions)

        self.assertEqual([v["tags"] for v in versions], [[], ["seed"]])


class TestCommitMessage(unittest.TestCase):
    def test_a_long_description_is_cut_to_keep_the_marker(self):
        version = {**_version("UHJvbXB0VmVyc2lvbjox", []), "description": "d" * 600}

        message = m._commit_message("p", version)

        self.assertLessEqual(len(message), m._COMMIT_MESSAGE_MAX)
        self.assertTrue(message.endswith(f"{m._MARKER}UHJvbXB0VmVyc2lvbjox"))


class TestImported(unittest.TestCase):
    def test_imported_versions_are_found_and_deleted_ones_skipped(self):
        langfuse = _Langfuse(
            {
                1: (200, {"commitMessage": f"seed {m._MARKER}A"}),
                2: (404, None),
                3: (200, {"commitMessage": f"{m._MARKER}C"}),
            }
        )

        self.assertEqual(m._imported(langfuse, "p"), {"A", "C"})

    def test_a_failed_read_stops_the_import_rather_than_importing_twice(self):
        langfuse = _Langfuse({1: (200, {"commitMessage": ""}), 2: (503, "unavailable")})

        with self.assertRaises(SystemExit):
            m._imported(langfuse, "p")


class TestUrls(unittest.TestCase):
    def test_only_http_urls_are_opened(self):
        with self.assertRaises(SystemExit):
            m._Http("file:///etc/passwd")
        self.assertEqual(
            m._Http("http://localhost:3000").base_url, "http://localhost:3000/"
        )


if __name__ == "__main__":
    unittest.main()
