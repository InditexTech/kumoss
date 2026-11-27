// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package cli holds the resolved context shared by the root command and every
// subcommand. It sits below both so neither has to import the other.
package cli

import (
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// Flags is built once in the root's PersistentPreRunE, so no command resolves
// flags for itself.
type Flags struct {
	Home home.Home

	// HomeOverride is the raw --home value, "" when unset. init and home read
	// it to decide whether to persist the choice.
	HomeOverride string

	// Foreground keeps `up` attached: logs stream until Ctrl-C, which also
	// stops the stack. Read by init and run.
	Foreground bool

	// HostCerts trusts this host's CA roots, for a TLS-inspecting proxy.
	HostCerts bool
}

// RegisterHome adds --home. NOT called by any command today: one home per user
// is the supported setup, so the flag is off everywhere and `kumoss init --home`
// is rejected. The resolution order (flag, KUMOSS_HOME, pointer, default) is
// unchanged, so re-enabling it means calling this from the commands that should
// accept it — init and home are the two that act on the answer.
func (f *Flags) RegisterHome(cmd *cobra.Command) {
	cmd.Flags().StringVar(&f.HomeOverride, "home", "", "managed home directory (default ~/.kumoss)")
}

// RegisterInit adds the flags only init acts on, local for the same reason.
func (f *Flags) RegisterInit(cmd *cobra.Command) {
	f.RegisterForeground(cmd)
	cmd.Flags().BoolVar(&f.HostCerts, "certs", false,
		"trust this host's CA roots in core and searxng (TLS-inspecting proxy)")
	// The name it shipped under, so an existing script keeps working.
	cmd.Flags().SetNormalizeFunc(func(_ *pflag.FlagSet, name string) pflag.NormalizedName {
		if name == "host-certs" {
			return "certs"
		}
		return pflag.NormalizedName(name)
	})
}

// RegisterForeground is shared by init and run, the two commands that start
// the stack. --host-certs is not: it only changes a file init writes.
func (f *Flags) RegisterForeground(cmd *cobra.Command) {
	cmd.Flags().BoolVar(&f.Foreground, "foreground", false,
		"stream the stack's logs instead of detaching; Ctrl-C also stops it")
}
