// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
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
		os.Exit(1)
	}
}

func NewRootCmd() *cobra.Command {
	var (
		flagHome string
		flagJSON bool
		flagYes  bool
		envFlags cli.Flags
	)

	root := &cobra.Command{
		Use:           "kumoss",
		Short:         "Kumoss CLI",
		Long:          "Kumoss CLI - A tool to install and operate Kumoss stack",
		Version:       buildinfo.Version,
		SilenceUsage:  true,
		SilenceErrors: true,
		PersistentPreRunE: func(_ *cobra.Command, _ []string) error {
			envFlags = cli.Flags{Home: home.New(flagHome), JSON: flagJSON, Yes: flagYes, HomeFlag: flagHome}
			return nil
		},
	}

	root.PersistentFlags().StringVar(&flagHome, "home", "", "managed home directory (default ~/.kumoss)")
	root.PersistentFlags().BoolVarP(&flagJSON, "json", "j", false, "machine-readable output")
	root.PersistentFlags().BoolVarP(&flagYes, "yes", "y", false, "assume yes for confirmations")

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
