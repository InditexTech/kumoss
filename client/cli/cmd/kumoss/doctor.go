// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

func NewDoctorCmd(root *cobra.Command, _ *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "doctor",
		Short: "Show the health status of the Kumoss CLI environment (not implemented)",
		Long: "Show the health status of the Kumoss CLI environment.\n\n" +
			"Not implemented yet: the command currently does nothing.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return nil
		},
	}
	root.AddCommand(cmd)
	return cmd
}
