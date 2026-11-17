// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/pipeline"
	"github.com/spf13/cobra"
)

func NewDoctorCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "doctor",
		Short: "Check the machine and the generated files before starting the stack",
		Long: "Check what the stack needs from the machine.\n\n" +
			"Reports whether docker is installed, whether Compose is v2, whether the\n" +
			"daemon answers, whether the managed home is writable, and whether the\n" +
			"generated files still agree with kumoss.yaml. Every check is printed, so\n" +
			"one failure does not hide the rest; the command exits non-zero when any\n" +
			"of them fails.\n\n" +
			"`kumoss run` makes the same file checks before starting, so doctor is for\n" +
			"when the stack will not start or nothing has been installed yet.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			// Resolve again for the Source: flags.Home carries the root only,
			// and a missing home names --home differently from the default.
			h, src := home.Resolve(flags.HomeOverride)
			return pipeline.RunDoctor(cmd.Context(), pipeline.DoctorOptions{
				Home:   h,
				Source: src,
				Out:    cmd.OutOrStdout(),
			})
		},
	}
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}
