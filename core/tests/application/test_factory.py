# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from src.application.factory import HandlerFactory
from src.application.dto import SessionContext


class TestHandlerFactoryShape(unittest.TestCase):
    def test_factory_takes_session_context_and_call_dir(self):
        ctx = SessionContext(
            session_id=uuid4(),
            user_id="u",
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
            history=[],
            is_first_call=True,
        )
        call_dir = Path(tempfile.mkdtemp())
        f = HandlerFactory(session_ctx=ctx, call_dir=call_dir, q="x")
        self.assertIs(f.session_ctx, ctx)
        self.assertEqual(f.call_dir, call_dir)
        self.assertEqual(f.q, "x")


class TestFactoryHandlerInjection(unittest.TestCase):
    def test_crud_handler_receives_session_ctx(self):
        ctx = SessionContext(
            session_id=uuid4(),
            user_id="u",
            repo_uri="file:///tmp/x.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
            history=[],
            is_first_call=True,
        )
        call_dir = Path(tempfile.mkdtemp())
        # Make the call_dir look like a git checkout so file_utils doesn't choke.
        (call_dir / ".git").mkdir()
        # FileSystemUtils scans for a subdir matching the environment name.
        (call_dir / "dev").mkdir()
        f = HandlerFactory(session_ctx=ctx, call_dir=call_dir, q="x")
        h = f.get_terraform_crud_handler()
        self.assertIs(h._TerraformCRUDHandler__ctx, ctx)
