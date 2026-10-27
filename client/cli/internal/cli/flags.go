// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package cli holds the resolved context shared by the root command and every
// subcommand. It sits below both so neither has to import the other.
package cli

import "github.com/InditexTech/kumoss/client/cli/internal/home"

// Flags is the resolved, read-only context every subcommand receives. It is
// built once in the root's PersistentPreRunE, so no command resolves flags.
type Flags struct {
	Home home.Home
	JSON bool
	Yes  bool

	// HomeFlag is the raw --home value: "" when the user did not pass it.
	// Only init consults it, to decide whether to persist the choice.
	HomeFlag string
}
