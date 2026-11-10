// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"runtime"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/release"
	"github.com/spf13/cobra"
)

func NewSelfInstallCmd(root *cobra.Command, _ *cli.Flags) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "self-install",
		Short: "Download and run the current install.sh",
		Long: "Download and run install.sh.\n\n" +
			"Upgrades in place without pasting the curl | bash line again. It verifies\n" +
			"the archive checksum and replaces the binary exactly like the installer\n" +
			"does, and needs curl or wget on PATH for the same reason the installer\n" +
			"does: the script downloads the release itself.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			ctx := cmd.Context()
			script, err := release.Script(ctx)
			if err != nil {
				return err
			}
			return runBash(ctx, cmd, script)
		},
	}
	root.AddCommand(cmd)
	return cmd
}

// runBash pipes the script to bash; it is never written to disk.
func runBash(ctx context.Context, cmd *cobra.Command, script []byte) error {
	if runtime.GOOS == "windows" {
		return fmt.Errorf("self-install is not supported on native Windows; use WSL2")
	}
	path, err := exec.LookPath("bash")
	if err != nil {
		return fmt.Errorf("bash not found: %w", err)
	}
	c := exec.CommandContext(ctx, path)
	c.Stdin = bytes.NewReader(script)
	c.Stdout = cmd.OutOrStdout()
	c.Stderr = cmd.ErrOrStderr()
	c.Env = os.Environ()
	if err := c.Run(); err != nil {
		return fmt.Errorf("install.sh: %w", err)
	}
	return nil
}
