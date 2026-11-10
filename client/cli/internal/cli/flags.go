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

// Flags is built once in the root's PersistentPreRunE, so no command resolves
// flags for itself.
type Flags struct {
	Home home.Home

	// HomeOverride is the raw --home value, "" when unset. init and home read
	// it to decide whether to persist the choice.
	HomeOverride string

	// Foreground keeps `up` attached: logs stream until Ctrl-C, which also
	// stops the stack. Only init reads it.
	Foreground bool

	// HostCerts trusts this host's CA roots, for a TLS-inspecting proxy.
	HostCerts bool
}

// RegisterHome is local, not persistent: a global --home would be accepted by
// commands that ignore it and silently do nothing.
func (f *Flags) RegisterHome(cmd *cobra.Command) {
	cmd.Flags().StringVar(&f.HomeOverride, "home", "", "managed home directory (default ~/.kumoss)")
}

// RegisterInit adds the flags only init acts on, local for the same reason.
func (f *Flags) RegisterInit(cmd *cobra.Command) {
	cmd.Flags().BoolVar(&f.Foreground, "foreground", false,
		"stream the stack's logs instead of detaching; Ctrl-C also stops it")
	cmd.Flags().BoolVar(&f.HostCerts, "host-certs", false,
		"trust this host's CA roots in core and searxng (TLS-inspecting proxy)")
}
