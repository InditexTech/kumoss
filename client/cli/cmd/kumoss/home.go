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
		Short: "Print (and persist or reset) the resolved Kumoss home directory",
		Long: "Print the resolved Kumoss home directory and how it was chosen.\n\n" +
			"Without --home the directory is read from, in order: the --home flag,\n" +
			"KUMOSS_HOME, the pointer file written by a previous --home, then ~/.kumoss.\n\n" +
			"With --home <dir> the given directory is resolved, printed, and remembered\n" +
			"for later invocations (the same pointer `kumoss init` writes).\n\n" +
			"With --reset the remembered pointer is removed, restoring the default\n" +
			"resolution (KUMOSS_HOME, then ~/.kumoss).",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if reset {
				if err := home.ClearPointer(); err != nil {
					return err
				}
				// flags.Home was resolved before the pointer was cleared; re-resolve
				// so the printed value reflects the restored default.
				return printHome(cmd, home.FromFlag(flags.HomeFlag), flags.JSON)
			}
			// Only an explicit --home is persisted; otherwise there is nothing
			// to remember beyond the default.
			if flags.HomeFlag != "" {
				if err := home.SetPointer(flags.Home.Root); err != nil {
					return err
				}
			}
			return printHome(cmd, flags.Home, flags.JSON)
		},
	}
	cmd.Flags().BoolVar(&reset, "reset", false, "forget the persisted --home and restore the default")
	root.AddCommand(cmd)
	return cmd
}

func printHome(cmd *cobra.Command, h home.Home, json bool) error {
	if json {
		fmt.Fprintf(cmd.OutOrStdout(), `{"root":%q}`+"\n", h.Root)
		return nil
	}
	fmt.Fprintln(cmd.OutOrStdout(), h.Root)
	return nil
}
