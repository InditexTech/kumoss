// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/spf13/cobra"
)

func NewDoctorCmd(root *cobra.Command) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "doctor",
		Short: "Show the health status of the Kumoss CLI environment",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return nil
		},
	}
	root.AddCommand(cmd)
	return cmd
}
