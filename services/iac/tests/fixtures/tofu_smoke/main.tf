# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Hermetic smoke fixture: `terraform_data` is built into the engine
# (terraform.io/builtin/terraform), so init / validate / plan / show /
# apply run with no provider downloads, no network, and no cloud
# credentials.

resource "terraform_data" "probe" {
  input = "nebula-iac-smoke"
}
