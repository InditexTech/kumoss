// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

func NewVersionCmd(root *cobra.Command, _ *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "version",
		Short: "Print the version number of Kumoss CLI and the checked-out stack tag",
		RunE: func(cmd *cobra.Command, _ []string) error {
			fmt.Fprintf(cmd.OutOrStdout(), "kumoss %s\n", buildinfo.Version)
			return nil
		},
	}
	root.AddCommand(cmd)
	return cmd
}
