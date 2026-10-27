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
		Short: "Initialize the Kumoss CLI environment",
		Long: "Initialize the Kumoss CLI environment, setting up necessary configurations and directories.\n" +
			"And launching the TUI for further interactions.",
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
	return cmd
}
