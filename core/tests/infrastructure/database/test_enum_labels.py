# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
import unittest

from sqlalchemy.dialects import postgresql

from src.infrastructure.database.database import enum_label_statements
from src.infrastructure.database.models import Base


class TestEnumLabelStatements(unittest.TestCase):
    def setUp(self):
        self.statements = enum_label_statements(Base.metadata, postgresql.dialect())

    def test_adds_every_terraform_provider_label(self):
        # Native enums store member names, so an existing database needs
        # the VMWARE label before it accepts a vmware session.
        for label in ("AZURE", "GCP", "AWS", "OCI", "K8S", "VMWARE"):
            self.assertIn(
                f"ALTER TYPE terraformprovider ADD VALUE IF NOT EXISTS '{label}'",
                self.statements,
            )

    def test_covers_each_enum_type_once(self):
        self.assertEqual(len(self.statements), len(set(self.statements)))
        self.assertTrue(
            any(s.startswith("ALTER TYPE sessionstatus ") for s in self.statements)
        )


if __name__ == "__main__":
    unittest.main()
