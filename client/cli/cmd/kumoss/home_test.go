// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// runHome mirrors NewRootCmd's PersistentPreRunE, which resolves the home after
// parsing; without it the command prints an empty path. KUMOSS_HOME is how a
// test picks another home: no command registers --home.
func runHome(t *testing.T, args ...string) string {
	t.Helper()
	var flags cli.Flags
	root := &cobra.Command{
		Use: "kumoss",
		PersistentPreRunE: func(*cobra.Command, []string) error {
			// No --home on the command, so only KUMOSS_HOME can set this.
			flags.Home = home.FromFlag(os.Getenv("KUMOSS_HOME"))
			return nil
		},
	}
	NewHomeCmd(root, &flags)

	var out bytes.Buffer
	root.SetOut(&out)
	root.SetErr(&out)
	root.SetArgs(append([]string{"home"}, args...))
	if err := root.Execute(); err != nil {
		t.Fatalf("home %v: %v", args, err)
	}
	return out.String()
}

// isolateHome keeps the pointer and the default out of the real home.
func isolateHome(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(dir, ".config"))
	t.Setenv("KUMOSS_HOME", "")
	return dir
}

// With no flags the command reports the default, and writes nothing.
func TestHomeDefaults(t *testing.T) {
	dir := isolateHome(t)
	got := runHome(t)
	if want := "Kumoss home is set to: " + filepath.Join(dir, ".kumoss"); !strings.Contains(got, want) {
		t.Errorf("output = %q, want %q", got, want)
	}
}

// A chosen home is remembered, so a later run without KUMOSS_HOME still finds
// it. --home is not registered, so the pointer is what carries the choice.
func TestHomePersistsTheChoice(t *testing.T) {
	isolateHome(t)
	chosen := filepath.Join(t.TempDir(), "elsewhere")
	if err := home.SetPointer(chosen); err != nil {
		t.Fatalf("SetPointer: %v", err)
	}

	if got := runHome(t); !strings.Contains(got, "Kumoss home is set to: "+chosen) {
		t.Errorf("first run = %q, want %s", got, chosen)
	}
	// KUMOSS_HOME unset: the pointer is the only source left.
	if got := runHome(t); !strings.Contains(got, "Kumoss home is set to: "+chosen) {
		t.Errorf("second run = %q, want the persisted %s", got, chosen)
	}
}

// --reset is gone with --home: nothing writes the pointer any more, and
// uninstall clears it. The command must reject it rather than ignore it.
func TestHomeHasNoFlags(t *testing.T) {
	isolateHome(t)
	t.Setenv("KUMOSS_HOME", filepath.Join(t.TempDir(), "elsewhere"))

	var flags cli.Flags
	root := &cobra.Command{Use: "kumoss"}
	NewHomeCmd(root, &flags)
	root.SetArgs([]string{"home", "--reset"})
	root.SetOut(&strings.Builder{})
	root.SetErr(&strings.Builder{})
	if err := root.Execute(); err == nil || !strings.Contains(err.Error(), "unknown flag") {
		t.Errorf("home --reset was accepted: %v", err)
	}
}

// KUMOSS_HOME outranks the default. --home still outranks it, but no command
// registers the flag, so it cannot be passed.
func TestHomePrecedence(t *testing.T) {
	isolateHome(t)
	t.Setenv("KUMOSS_HOME", "/from/env")
	if got := runHome(t); !strings.Contains(got, "/from/env") {
		t.Errorf("KUMOSS_HOME ignored: %q", got)
	}
}

// The flag is registered locally: `kumoss help --all` relies on this list.
func TestHomeRegistersOnlyItsFlags(t *testing.T) {
	var flags cli.Flags
	root := &cobra.Command{Use: "kumoss"}
	c := NewHomeCmd(root, &flags)

	names := []string{}
	c.Flags().VisitAll(func(f *pflag.Flag) { names = append(names, f.Name) })
	// Neither --home nor --reset: home is fixed per user, and uninstall
	// clears the pointer.
	if len(names) != 0 {
		t.Errorf("flags = %v, want none", names)
	}
}
