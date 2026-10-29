// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package cli holds the resolved context shared by the root command and every
// subcommand. It sits below both so neither has to import the other.
package cli

import (
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
)

// Flags is the resolved, read-only context every subcommand receives. It is
// built once in the root's PersistentPreRunE, so no command resolves flags.
type Flags struct {
	Home home.Home

	// HomeOverride is the raw --home value: "" when the user did not pass it.
	// Only init and home consult it, to decide whether to persist the choice.
	HomeOverride string
}

// RegisterHome adds the --home flag to a command that honours it. Only init
// and home do: registering it everywhere would accept the flag on commands
// that ignore it, silently doing nothing.
func (f *Flags) RegisterHome(cmd *cobra.Command) {
	cmd.Flags().StringVar(&f.HomeOverride, "home", "", "managed home directory (default ~/.kumoss)")
}
