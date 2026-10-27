// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
)

func NewInitCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "init",
		Short: "Create the Kumoss home directory skeleton",
		Long: "Create the Kumoss home directory skeleton.\n\n" +
			"Ensures the managed directories exist (the home root, src/, src/services/\n" +
			"and config/) and, when --home is given, persists that choice so later\n" +
			"invocations resolve it without repeating the flag.\n\n" +
			"Files are not written here: kumoss.yaml, config/config.yaml, the compose\n" +
			"override and the .env files are produced by their own commands.\n\n" +
			"Launches the TUI for further interactions.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if err := flags.Home.Ensure(); err != nil {
				return err
			}
			// Only an explicit --home is persisted; otherwise there is nothing
			// to remember beyond the default.
			if flags.HomeFlag != "" {
				if err := home.SetPointer(flags.Home.Root); err != nil {
					return err
				}
			}
			return nil
		},
	}
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}
