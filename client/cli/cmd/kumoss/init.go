// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/pipeline"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
	"github.com/spf13/cobra"
)

func NewInitCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	var dryRun bool
	cmd := &cobra.Command{
		Use:   "init",
		Short: "Install or reconfigure the Kumoss stack, and run it if desired",
		Long: "Install or reconfigure the Kumoss stack.\n\n" +
			"Ensures the managed directories exist (the home root, src/, src/services/\n" +
			"and config/) and, when --home is given, persists that choice so later\n" +
			"invocations resolve it without repeating the flag.\n\n" +
			"Then it fetches docker-compose.yml at the release tag, launches the TUI,\n" +
			"and writes kumoss.yaml, config/config.yaml, compose.override.yml and the\n" +
			".env files. Every step is idempotent: an existing install is offered a\n" +
			"reconfigure or keep, and running again fixes a failed run.\n\n" +
			"Finally it offers to pull the missing images and start the stack. That is\n" +
			"detached (`docker compose up -d`) unless --foreground is given, which\n" +
			"streams the logs until Ctrl-C also stops the stack.\n\n" +
			"With --dry-run the same questions are asked but nothing is written: no\n" +
			"directory, no file, no container. The files a real run would write are\n" +
			"printed instead, so a run can be reviewed before it touches the machine.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return pipeline.RunPipeline(cmd.Context(), pipeline.Options{
				Home:        flags.Home,
				PersistHome: flags.HomeOverride != "",
				Foreground:  flags.Foreground,
				HostCerts:   flags.HostCerts,
				DryRun:      dryRun,
				UI: &tui.Wizard{
					In:         cmd.InOrStdin(),
					Out:        cmd.OutOrStdout(),
					Accessible: false,
				},
				Out:  cmd.OutOrStdout(),
				Warn: cmd.ErrOrStderr(),
			})
		},
	}
	cmd.Flags().BoolVar(&dryRun, "dry-run", false,
		"ask everything, write nothing: print the files a real run would write")
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	flags.RegisterInit(cmd)
	return cmd
}
