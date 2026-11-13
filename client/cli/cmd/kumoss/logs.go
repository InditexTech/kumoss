// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/spf13/cobra"
)

func NewLogsCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	var follow bool
	var since string
	cmd := &cobra.Command{
		Use:   "logs [service…] [-f] [--since <duration>]",
		Short: "Show the stack's logs",
		Long: "Show the logs of the running stack, through `docker compose logs`.\n\n" +
			"With no service it shows every container. -f follows, --since limits\n" +
			"how far back to read (30m, 2h, 2026-01-02T15:04:05Z). Ctrl-C stops\n" +
			"following; the stack keeps running.",
		RunE: func(cmd *cobra.Command, args []string) error {
			c := &docker.Compose{
				ProjectDir: flags.Home.Root,
				Files:      []string{rel(flags.Home.Root, flags.Home.ComposeFile()), rel(flags.Home.Root, flags.Home.ComposeOverride())},
			}
			if err := c.Logs(cmd.Context(), follow, since, args...); err != nil {
				return fmt.Errorf("show logs: %w", err)
			}
			return nil
		},
	}
	cmd.Flags().BoolVarP(&follow, "follow", "f", false, "follow the log output")
	cmd.Flags().StringVar(&since, "since", "", "only logs since this time (30m, 2h, a timestamp)")
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}
