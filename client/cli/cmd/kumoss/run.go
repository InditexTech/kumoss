// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/pipeline"
	"github.com/spf13/cobra"
)

func NewRunCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "run",
		Short: "Start an already-configured stack",
		Long: "Start the Kumoss stack from the files already in the managed home.\n\n" +
			"run writes nothing. It first checks that every answer recorded in\n" +
			"kumoss.yaml is present and matches config/config.yaml and the .env\n" +
			"files, and that the credentials the configured LLM provider and clouds\n" +
			"need are filled in. Anything missing or edited by hand is printed with\n" +
			"the `kumoss config <section>` that rewrites it, and nothing is started.\n" +
			"A home with no kumoss.yaml has nothing to check against: install it\n" +
			"with `kumoss init` first.\n\n" +
			"Once the checks pass it starts the whole stack. With no containers yet\n" +
			"it pulls the images first; with containers already there it skips the\n" +
			"pull and forces a recreate of the stack when a generated file changed\n" +
			"after the container that mounts it, since compose compares the service\n" +
			"definition and would otherwise keep the old values.\n\n" +
			"That is detached (`docker compose up -d`) unless --foreground is given,\n" +
			"which streams the logs until Ctrl-C also stops the stack.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return pipeline.RunStack(cmd.Context(), pipeline.RunOptions{
				Home:       flags.Home,
				Foreground: flags.Foreground,
				Out:        cmd.OutOrStdout(),
			})
		},
	}
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	flags.RegisterForeground(cmd)
	return cmd
}
