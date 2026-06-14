# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from src.shared.utils.repo_uri import derive_project_name


class TestDeriveProjectName(unittest.TestCase):
    def test_https_with_dot_git(self):
        self.assertEqual(derive_project_name("https://github.com/foo/bar.git"), "bar")

    def test_https_without_dot_git(self):
        self.assertEqual(derive_project_name("https://github.com/foo/bar"), "bar")

    def test_ssh_url(self):
        self.assertEqual(derive_project_name("git@github.com:foo/bar.git"), "bar")

    def test_file_url(self):
        self.assertEqual(derive_project_name("file:///srv/repos/quux.git"), "quux")

    def test_trailing_slash(self):
        self.assertEqual(derive_project_name("https://example.com/team/baz/"), "baz")
