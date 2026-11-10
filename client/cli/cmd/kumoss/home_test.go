// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// runHome mirrors NewRootCmd's PersistentPreRunE, which resolves --home after
// parsing; without it the command prints an empty path.
func runHome(t *testing.T, args ...string) string {
	t.Helper()
	var flags cli.Flags
	root := &cobra.Command{
		Use: "kumoss",
		PersistentPreRunE: func(*cobra.Command, []string) error {
			flags.Home = home.FromFlag(flags.HomeOverride)
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

// --home is persisted, so a later run without it still finds the choice.
func TestHomePersistsTheChoice(t *testing.T) {
	isolateHome(t)
	chosen := filepath.Join(t.TempDir(), "elsewhere")

	if got := runHome(t, "--home", chosen); !strings.Contains(got, "Kumoss home persisted to: "+chosen) {
		t.Errorf("persist output = %q", got)
	}
	// A second run with no flag resolves through the pointer.
	if got := runHome(t); !strings.Contains(got, "Kumoss home is set to: "+chosen) {
		t.Errorf("second run = %q, want the persisted %s", got, chosen)
	}
}

// --reset drops the pointer and reports the restored default.
func TestHomeReset(t *testing.T) {
	dir := isolateHome(t)
	runHome(t, "--home", filepath.Join(t.TempDir(), "elsewhere"))

	got := runHome(t, "--reset")
	if want := "Kumoss home is reset to: " + filepath.Join(dir, ".kumoss"); !strings.Contains(got, want) {
		t.Errorf("reset output = %q, want %q", got, want)
	}
	// The pointer must be gone: a plain run no longer finds the old choice.
	if got := runHome(t); !strings.Contains(got, filepath.Join(dir, ".kumoss")) {
		t.Errorf("after reset = %q", got)
	}
}

// KUMOSS_HOME outranks the default, and --home outranks KUMOSS_HOME.
func TestHomePrecedence(t *testing.T) {
	isolateHome(t)
	t.Setenv("KUMOSS_HOME", "/from/env")
	if got := runHome(t); !strings.Contains(got, "/from/env") {
		t.Errorf("KUMOSS_HOME ignored: %q", got)
	}
	if got := runHome(t, "--home", "/from/flag"); !strings.Contains(got, "/from/flag") {
		t.Errorf("--home ignored: %q", got)
	}
}

// The flag is registered locally: `kumoss help --all` relies on this list.
func TestHomeRegistersOnlyItsFlags(t *testing.T) {
	var flags cli.Flags
	root := &cobra.Command{Use: "kumoss"}
	c := NewHomeCmd(root, &flags)

	names := []string{}
	c.Flags().VisitAll(func(f *pflag.Flag) { names = append(names, f.Name) })
	if strings.Join(names, ",") != "home,reset" {
		t.Errorf("flags = %v, want [home reset]", names)
	}
}
