// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/spf13/cobra"
)

func NewConfigCmd(root *cobra.Command) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "config",
		Short: "Show the configuration of the Kumoss CLI environment",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return nil
		},
	}
	root.AddCommand(cmd)
	return cmd
}
