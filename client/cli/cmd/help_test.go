// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bytes"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

// runHelp executes the help command with args and returns its output.
func runHelp(t *testing.T, args ...string) string {
	t.Helper()
	root := NewRootCmd()
	var out bytes.Buffer
	root.SetOut(&out)
	root.SetErr(&out)
	root.SetArgs(append([]string{"help"}, args...))
	if err := root.Execute(); err != nil {
		t.Fatalf("help %v: %v", args, err)
	}
	return out.String()
}

// --all groups each command's own flags under it, and a command with no flags
// is still listed, so the reader knows it was considered.
func TestHelpAllGroupsFlagsByCommand(t *testing.T) {
	got := runHelp(t, "--all")

	for _, want := range []string{
		"Flags by command:",
		"\ninit\n",
		"--foreground",
		"--host-certs",
		"--home string",
		"\nhome\n",
		"--reset",
		"config, doctor, logs, status, version",
		"(no flags)",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("output missing %q:\n%s", want, got)
		}
	}
	// cobra's own commands are not ours to advertise.
	if strings.Contains(got, "completion") {
		t.Errorf("output lists cobra's completion command:\n%s", got)
	}
}

// A command argument still wins over --all, so `help --all init` is not a
// surprise.
func TestHelpWithCommandStillPrintsThatCommand(t *testing.T) {
	got := runHelp(t, "--all", "init")
	if strings.Contains(got, "Flags by command:") {
		t.Errorf("--all overrode the command argument:\n%s", got)
	}
	if !strings.Contains(got, "kumoss init [flags]") {
		t.Errorf("init help not printed:\n%s", got)
	}
}

// The listing must come from the live tree, not a hand-kept list: a command
// added later shows up without touching help.go.
func TestHelpAllReflectsNewCommands(t *testing.T) {
	root := NewRootCmd()
	extra := &cobra.Command{Use: "extra", RunE: func(*cobra.Command, []string) error { return nil }}
	extra.Flags().String("thing", "", "a thing")
	root.AddCommand(extra)

	var out bytes.Buffer
	root.SetOut(&out)
	root.SetArgs([]string{"help", "--all"})
	if err := root.Execute(); err != nil {
		t.Fatalf("help --all: %v", err)
	}
	if !strings.Contains(out.String(), "--thing string") {
		t.Errorf("new command's flag missing:\n%s", out.String())
	}
}
