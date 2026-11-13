// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
)

func NewUninstallCmd(root *cobra.Command, flags *cli.Flags) *cobra.Command {
	var purge bool
	cmd := &cobra.Command{
		Use:   "uninstall [--purge]",
		Short: "Stop the stack and delete the managed home",
		Long: "Stop the Kumoss stack and delete the managed home directory.\n\n" +
			"It runs `docker compose down -v` against the managed home, which stops\n" +
			"the containers and deletes the data volumes, then removes the home and\n" +
			"the persisted --home pointer. The binary and the pulled images are left\n" +
			"alone; remove ~/.local/bin/kumoss yourself for a full uninstall.\n\n" +
			"With --purge it does the same without asking first.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			h := flags.Home
			if _, err := os.Stat(h.Root); os.IsNotExist(err) {
				// Still drop the pointer, or a later init resolves to a
				// directory that is gone.
				if err := home.ClearPointer(); err != nil {
					return err
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Nothing to uninstall: %s does not exist.\n", h.Root)
				return nil
			}
			if !purge {
				ok, err := confirm(cmd, fmt.Sprintf("Stop the stack and delete %s, including its data volumes?", h.Root))
				if err != nil {
					return err
				}
				if !ok {
					fmt.Fprintln(cmd.OutOrStdout(), "Aborted; nothing was removed.")
					return nil
				}
			}

			// A half-written home may lack the compose files, and then there
			// is nothing running to stop.
			if _, err := os.Stat(h.ComposeFile()); err == nil {
				c := &docker.Compose{
					ProjectDir: h.Root,
					Files:      []string{rel(h.Root, h.ComposeFile()), rel(h.Root, h.ComposeOverride())},
				}
				if err := c.Down(cmd.Context(), true); err != nil {
					return err
				}
			} else {
				fmt.Fprintf(cmd.ErrOrStderr(), "No %s; skipping docker compose down.\n", h.ComposeFile())
			}

			if err := os.RemoveAll(h.Root); err != nil {
				return err
			}
			if err := home.ClearPointer(); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Removed %s.\n", h.Root)
			return nil
		},
	}
	cmd.Flags().BoolVar(&purge, "purge", false, "do not ask for confirmation")
	root.AddCommand(cmd)
	flags.RegisterHome(cmd)
	return cmd
}

// rel is filepath.Rel with a fallback, kept local so cmd does not import the
// pipeline just for one call.
func rel(base, path string) string {
	if r, err := filepath.Rel(base, path); err == nil {
		return r
	}
	return path
}

// confirm reads one line from stdin. EOF or anything but y/yes is a no, so a
// piped run never deletes anything by accident.
func confirm(cmd *cobra.Command, question string) (bool, error) {
	fmt.Fprintf(cmd.OutOrStdout(), "%s [y/N]: ", question)
	line, err := bufio.NewReader(cmd.InOrStdin()).ReadString('\n')
	if err != nil && line == "" {
		return false, nil
	}
	switch strings.ToLower(strings.TrimSpace(line)) {
	case "y", "yes":
		return true, nil
	}
	return false, nil
}
