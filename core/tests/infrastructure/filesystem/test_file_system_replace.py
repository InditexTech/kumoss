# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import shutil
import tempfile
import unittest
from pathlib import Path

from src.infrastructure.exceptions import SearchReplaceBlockError
from src.infrastructure.filesystem.file_system import FileSystemUtils


class TestReplaceInFile(unittest.TestCase):
    @staticmethod
    def _block(search: str, replace: str) -> str:
        return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"

    def setUp(self):
        self.original = (
            'resource "aws_s3_bucket" "a" {\n  bucket = "a"\n}\n\n'
            + 'resource "aws_s3_bucket" "b" {\n  bucket = "b"\n}\n'
        )
        self.root = Path(tempfile.mkdtemp())
        self.file = self.root / "main.tf"
        self.file.write_text(self.original, encoding="utf-8")
        self.fs = FileSystemUtils(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def _assert_rejected(self, diff: str, error_code: int, fragment: str):
        with self.assertRaises(SearchReplaceBlockError) as ctx:
            self.fs.replace_in_file("main.tf", diff)
        self.assertEqual(ctx.exception.error_code, error_code)
        self.assertIn(fragment, ctx.exception.message)
        self.assertEqual(self.file.read_text(encoding="utf-8"), self.original)

    def test_applies_multiple_blocks(self):
        diff = self._block('bucket = "a"', 'bucket = "a2"') + self._block(
            'bucket = "b"', 'bucket = "b2"'
        )
        self.assertTrue(self.fs.replace_in_file("main.tf", diff))
        content = self.file.read_text(encoding="utf-8")
        self.assertIn('bucket = "a2"', content)
        self.assertIn('bucket = "b2"', content)

    def test_empty_replace_deletes(self):
        self.assertTrue(
            self.fs.replace_in_file("main.tf", self._block('bucket = "a"', ""))
        )
        self.assertNotIn('bucket = "a"', self.file.read_text(encoding="utf-8"))

    def test_tolerates_code_fences_and_blank_lines(self):
        diff = "\n```\n" + self._block('bucket = "a"', 'bucket = "z"') + "```\n\n"
        self.assertTrue(self.fs.replace_in_file("main.tf", diff))
        self.assertIn('bucket = "z"', self.file.read_text(encoding="utf-8"))

    def test_empty_diff(self):
        self._assert_rejected("", 400, "No SEARCH/REPLACE blocks")
        self._assert_rejected("  \n\n", 400, "No SEARCH/REPLACE blocks")

    def test_missing_separator(self):
        diff = '<<<<<<< SEARCH\nbucket = "a"\n>>>>>>> REPLACE\n'
        self._assert_rejected(diff, 400, "missing '=======' separator")

    def test_multiple_separators(self):
        diff = '<<<<<<< SEARCH\nbucket = "a"\n=======\nx\n=======\ny\n>>>>>>> REPLACE\n'
        self._assert_rejected(diff, 400, "more than one '======='")

    def test_unclosed_block(self):
        diff = '<<<<<<< SEARCH\nbucket = "a"\n=======\nx\n'
        self._assert_rejected(diff, 400, "not closed with '>>>>>>> REPLACE'")

    def test_nested_search_marker(self):
        diff = '<<<<<<< SEARCH\nbucket = "a"\n<<<<<<< SEARCH\n'
        self._assert_rejected(diff, 400, "before the previous block was closed")

    def test_separator_outside_block(self):
        self._assert_rejected("=======\n", 400, "'=======' found outside a block")

    def test_replace_marker_outside_block(self):
        self._assert_rejected(
            ">>>>>>> REPLACE\n", 400, "'>>>>>>> REPLACE' found outside a block"
        )

    def test_missing_search_marker(self):
        diff = 'bucket = "a"\n=======\nx\n>>>>>>> REPLACE\n'
        self._assert_rejected(diff, 400, "unexpected text outside a block")

    def test_stray_text_after_block(self):
        diff = self._block('bucket = "a"', "x") + "done!\n"
        self._assert_rejected(diff, 400, "Block 2 (diff line 6)")

    def test_empty_search(self):
        self._assert_rejected(self._block("   ", "x"), 400, "SEARCH section is empty")

    def test_search_not_found(self):
        self._assert_rejected(
            self._block('bucket = "missing"', "x"),
            404,
            "Block 1: SEARCH content not found",
        )

    def test_search_matches_multiple_locations(self):
        self._assert_rejected(
            self._block('resource "aws_s3_bucket"', "x"), 400, "matches 2 locations"
        )

    def test_later_block_failure_leaves_file_untouched(self):
        diff = self._block('bucket = "a"', 'bucket = "a2"') + self._block("nope", "x")
        self._assert_rejected(diff, 404, "Block 2")

    def test_structural_error_reported_before_matching(self):
        diff = self._block("nope", "x") + "=======\n"
        self._assert_rejected(diff, 400, "Block 2")

    def test_snippet_is_truncated(self):
        long_search = "x" * 200
        with self.assertRaises(SearchReplaceBlockError) as ctx:
            self.fs.replace_in_file("main.tf", self._block(long_search, "y"))
        self.assertIn("x" * 80 + "...", ctx.exception.message)
        self.assertNotIn("x" * 81, ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
