// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

func NewVersionCmd(root *cobra.Command, _ *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "version",
		Short: "Print the Kumoss CLI version and the stack tag it targets",
		Long: "Print the Kumoss CLI version and the stack tag it targets.\n\n" +
			"The tag is the release version for release builds, else the KUMOSS_TAG\n" +
			"env var, else \"main\".",
		RunE: func(cmd *cobra.Command, _ []string) error {
			_, err := fmt.Fprintf(cmd.OutOrStdout(), "kumoss %s (stack %s)\n", buildinfo.Version, buildinfo.KumossTag())
			return err
		},
	}
	root.AddCommand(cmd)
	return cmd
}
