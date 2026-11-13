// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bufio"
	"fmt"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/pipeline"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
	"github.com/spf13/cobra"
)

func NewConfigCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "config <section>",
		Short: "Reopen one wizard section and apply it",
		Long: "Reopen one wizard section, prefilled from the current files.\n\n" +
			"Sections: llm, git, cloud, engine, state, notifications, secrets.\n\n" +
			"It shows a diff of the generated files with the secrets masked and,\n" +
			"on confirmation, writes them and recreates only the containers that\n" +
			"read them: llm and git recreate core; cloud and engine recreate iac;\n" +
			"state recreates core and iac; notifications recreates core and\n" +
			"notifications; secrets rotates a token pair. `docker compose restart`\n" +
			"would keep the old environment, so the containers are recreated.\n\n" +
			"With no section it lists them.",
		Args: cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 {
				for _, s := range pipeline.Sections {
					fmt.Fprintf(cmd.OutOrStdout(), "%-14s recreates %v\n", s.Name, s.Services)
				}
				return nil
			}
			in := bufio.NewReader(cmd.InOrStdin())
			return pipeline.RunConfig(cmd.Context(), pipeline.ConfigOptions{
				Home:    flags.Home,
				Section: args[0],
				UI: &tui.Wizard{
					In:  in,
					Out: cmd.OutOrStdout(),
				},
				Confirm: func(diff string) (bool, error) {
					fmt.Fprint(cmd.OutOrStdout(), diff)
					fmt.Fprint(cmd.OutOrStdout(), "\nWrite these changes and recreate the containers? [y/N]: ")
					line, err := in.ReadString('\n')
					if err != nil && line == "" {
						return false, nil
					}
					switch strings.ToLower(strings.TrimSpace(line)) {
					case "y", "yes":
						return true, nil
					}
					return false, nil
				},
				Out:  cmd.OutOrStdout(),
				Warn: cmd.ErrOrStderr(),
			})
		},
	}
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}
