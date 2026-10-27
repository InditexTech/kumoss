// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"
	"os"

	cmd "github.com/InditexTech/kumoss/client/cli/cmd/kumoss"
	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
)

func Execute(command *cobra.Command) {
	err := command.Execute()
	if err != nil {
		// SilenceErrors is set so cobra does not also print usage; report the
		// error itself, or a parse failure exits 1 with no explanation.
		fmt.Fprintln(os.Stderr, "kumoss:", err)
		os.Exit(1)
	}
}

func NewRootCmd() *cobra.Command {
	var envFlags cli.Flags

	root := &cobra.Command{
		Use:           "kumoss",
		Short:         "Kumoss CLI",
		Long:          "Kumoss CLI - A tool to install and operate Kumoss stack",
		Version:       buildinfo.Version,
		SilenceUsage:  true,
		SilenceErrors: true,
		PersistentPreRunE: func(_ *cobra.Command, _ []string) error {
			// HomeFlag is bound by whichever command registered --home (empty
			// elsewhere); resolve it here, once parsing is done.
			envFlags.Home = home.FromFlag(envFlags.HomeFlag)
			return nil
		},
	}

	AddChildCommands(root, &envFlags)

	return root
}

func AddChildCommands(rootCmd *cobra.Command, env *cli.Flags) {
	cmd.NewVersionCmd(rootCmd, env)
	cmd.NewInitCmd(rootCmd, env)
	cmd.NewStatusCmd(rootCmd, env)
	cmd.NewLogsCmd(rootCmd, env)
	cmd.NewConfigCmd(rootCmd, env)
	cmd.NewDoctorCmd(rootCmd, env)
	cmd.NewHomeCmd(rootCmd, env)
}
