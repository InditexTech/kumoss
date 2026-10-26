// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"os"

	cmd "github.com/InditexTech/kumoss/cli/cmd/kumoss"
	"github.com/InditexTech/kumoss/cli/internal/buildinfo"
	"github.com/spf13/cobra"
)

func Execute(command *cobra.Command) {
	err := command.Execute()
	if err != nil {
		os.Exit(1)
	}
}

func NewRootCmd() *cobra.Command {
	root := &cobra.Command{
		Use:           "kumoss",
		Short:         "Kumoss CLI",
		Long:          "Kumoss CLI - A tool to install and operate Kumoss stack",
		Version:       buildinfo.Version,
		SilenceUsage:  true,
		SilenceErrors: true,
	}

	root.PersistentFlags().String("home", "", "managed home directory (default ~/.kumoss)")
	root.PersistentFlags().Bool("json", false, "machine-readable output")
	root.PersistentFlags().Bool("yes", false, "assume yes for confirmations")

	return root
}

func AddChildCommands(rootCmd *cobra.Command) {
	cmd.NewVersionCmd(rootCmd)
	cmd.NewInitCmd(rootCmd)
	cmd.NewStatusCmd(rootCmd)
	cmd.NewLogsCmd(rootCmd)
	cmd.NewConfigCmd(rootCmd)
	cmd.NewDoctorCmd(rootCmd)
}
