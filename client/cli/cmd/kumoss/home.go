// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

func NewHomeCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "home",
		Short: "Print the resolved Kumoss home directory",
		RunE: func(cmd *cobra.Command, _ []string) error {
			if flags.JSON {
				fmt.Fprintf(cmd.OutOrStdout(), `{"root":%q}`+"\n", flags.Home.Root)
				return nil
			}
			fmt.Fprintln(cmd.OutOrStdout(), flags.Home.Root)
			return nil
		},
	}
	root.AddCommand(cmd)
	return cmd
}
