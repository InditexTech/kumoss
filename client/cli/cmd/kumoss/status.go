// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/pipeline"
	"github.com/spf13/cobra"
)

func NewStatusCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show the stack's state, health and pending changes",
		Long: "Show the state of the Kumoss stack.\n\n" +
			"A table of every container with its state, uptime and restart count,\n" +
			"from `docker compose ps`. Then the core probe (/api/v1/auth/config) and\n" +
			"the sidecars' /healthz, the Kumoss tag the stack was built from, and the\n" +
			"optional pieces an init left unset.\n\n" +
			"Finally it names any generated file changed after its container was\n" +
			"created: compose compares the service definition, not the bytes of a\n" +
			"mounted file, so those changes are not live until a recreate.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return pipeline.RunStatus(cmd.Context(), pipeline.StatusOptions{
				Home: flags.Home,
				Out:  cmd.OutOrStdout(),
			})
		},
	}
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}
