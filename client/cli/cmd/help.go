// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"fmt"
	"io"
	"sort"
	"strings"
	"text/tabwriter"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// SetHelpCommand replaces cobra's generated help command with one that also
// answers --all. cobra builds its help command lazily, so this must run before
// Execute; `kumoss help init` keeps working exactly as before.
func SetHelpCommand(root *cobra.Command) {
	help := &cobra.Command{
		Use:   "help [command]",
		Short: "Help about any command",
		Long: "Help about any command.\n\n" +
			"With a command name it prints that command's help. With --all it lists\n" +
			"every command's own flags, grouped by command.",
		RunE: func(c *cobra.Command, args []string) error {
			all, err := c.Flags().GetBool("all")
			if err != nil {
				return err
			}
			// A command argument wins: the caller asked about one command.
			if len(args) == 0 && all {
				return printAllFlags(c.OutOrStdout(), root)
			}
			target, _, err := root.Find(args)
			if err != nil || target == nil {
				return fmt.Errorf("unknown command %q", strings.Join(args, " "))
			}
			return target.Help()
		},
	}
	help.Flags().Bool("all", false, "list every command's flags, grouped by command")
	root.SetHelpCommand(help)
}

// printAllFlags lists each command's own flags. Inherited flags are left out:
// the tree has no persistent flags today, and a child's inherited set would
// repeat them under every command.
func printAllFlags(w io.Writer, root *cobra.Command) error {
	if _, err := fmt.Fprintln(w, "Flags by command:"); err != nil {
		return err
	}
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
	var bare []string
	for _, c := range root.Commands() {
		// help and completion are cobra's own; the rest is what we ship.
		if c.Name() == "help" || c.Name() == "completion" {
			continue
		}
		var lines []string
		c.Flags().VisitAll(func(f *pflag.Flag) {
			if f.Hidden || f.Name == "help" {
				return
			}
			usage := f.Usage
			// --help is always present and its default is the empty string, so
			// only a real default is worth printing.
			if f.DefValue != "" && f.DefValue != "false" {
				usage += " (default " + f.DefValue + ")"
			}
			lines = append(lines, fmt.Sprintf("  --%s %s\t%s", f.Name, typeName(f), usage))
		})
		if len(lines) == 0 {
			bare = append(bare, c.Name())
			continue
		}
		sort.Strings(lines)
		if _, err := fmt.Fprintf(tw, "\n%s\n%s\n", c.Name(), strings.Join(lines, "\n")); err != nil {
			return err
		}
	}
	if len(bare) > 0 {
		sort.Strings(bare)
		if _, err := fmt.Fprintf(tw, "\n%s\n  (no flags)\n", strings.Join(bare, ", ")); err != nil {
			return err
		}
	}
	return tw.Flush()
}

// typeName is pflag's type placeholder for the usage line, matching what
// cobra prints: "string" for strings, nothing for bools.
func typeName(f *pflag.Flag) string {
	if f.Value.Type() == "bool" {
		return ""
	}
	return f.Value.Type()
}
