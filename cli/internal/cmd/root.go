// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/cli/internal/buildinfo"
	"github.com/spf13/cobra"
)

func Execute() error {
	return newRootCmd().Execute()
}

func newRootCmd() *cobra.Command {
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

	root.AddCommand(newVersionCmd())
	root.AddCommand(newInitCmd())
	root.AddCommand(newStatusCmd())
	root.AddCommand(newLogsCmd())
	root.AddCommand(newConfigCmd())
	root.AddCommand(newDoctorCmd())

	return root
}
