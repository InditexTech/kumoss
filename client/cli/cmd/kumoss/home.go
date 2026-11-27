// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
)

func NewHomeCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "home",
		Short: "Print the resolved Kumoss home directory",
		Long: "Print the resolved Kumoss home directory.\n\n" +
			"The path is taken from the first of: KUMOSS_HOME, the pointer file\n" +
			"written by a previous choice, then ~/.kumoss. Uninstall clears the\n" +
			"pointer itself, so there is no --reset to run.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			// Only an explicitly chosen home is worth remembering. HomeOverride
			// stays in the code for when --home is registered again.
			if flags.HomeOverride != "" {
				if err := home.SetPointer(flags.Home.Root); err != nil {
					return err
				}
				return printHome(cmd, flags.Home, "Kumoss home persisted to")
			}
			return printHome(cmd, flags.Home, "Kumoss home is set to")
		},
	}
	root.AddCommand(cmd)
	return cmd
}

func printHome(cmd *cobra.Command, h home.Home, msg string) error {
	_, err := fmt.Fprintf(cmd.OutOrStdout(), "%s: %s\n", msg, h.Root)
	return err
}
