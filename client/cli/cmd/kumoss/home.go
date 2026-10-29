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
	var reset bool
	cmd := &cobra.Command{
		Use:   "home [--home <dir> | --reset]",
		Short: "Print the resolved Kumoss home directory",
		Long: "Print the resolved Kumoss home directory.\n\n" +
			"The path is taken from the first of: the --home flag, KUMOSS_HOME, the\n" +
			"pointer file written by a previous --home, then ~/.kumoss.\n\n" +
			"With --home <dir> the given directory is resolved, printed, and the\n" +
			"choice is persisted for later invocations.\n\n" +
			"With --reset the persisted pointer is removed, restoring the default\n" +
			"resolution (KUMOSS_HOME, then ~/.kumoss).",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if reset {
				if err := home.ClearPointer(); err != nil {
					return err
				}
				// flags.Home was resolved before the pointer was cleared; re-resolve
				// so the printed value reflects the restored default.
				return printHome(cmd, home.FromFlag(flags.HomeOverride), "Kumoss home is reset to")
			}
			// Only an explicit --home is persisted; otherwise there is nothing
			// to remember beyond the default.
			if flags.HomeOverride != "" {
				if err := home.SetPointer(flags.Home.Root); err != nil {
					return err
				}
				return printHome(cmd, flags.Home, "Kumoss home persisted to")
			}
			return printHome(cmd, flags.Home, "Kumoss home is set to")
		},
	}
	cmd.Flags().BoolVar(&reset, "reset", false, "forget the persisted --home and restore the default")
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}

func printHome(cmd *cobra.Command, h home.Home, msg string) error {
	_, err := fmt.Fprintf(cmd.OutOrStdout(), "%s: %s\n", msg, h.Root)
	return err
}
