// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

func NewStatusCmd(root *cobra.Command, _ *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show the status of the Kumoss CLI environment",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return nil
		},
	}
	root.AddCommand(cmd)
	return cmd
}
