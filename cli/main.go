// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"github.com/InditexTech/kumoss/cli/cmd"
)

func main() {
	rootCmd := cmd.NewRootCmd()
	cmd.Execute(rootCmd)
}
