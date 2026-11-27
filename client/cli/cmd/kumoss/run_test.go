// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/spf13/cobra"
)

// The flags are local, not persistent: a global --foreground would be
// accepted by every command, including the ones that ignore it.
func TestRunCmdRegistersItsOwnFlags(t *testing.T) {
	var flags cli.Flags
	cmd := NewRunCmd(&cobra.Command{Use: "kumoss"}, &flags)

	// No --home: kept in the code, registered nowhere.
	for _, name := range []string{"foreground"} {
		if cmd.Flags().Lookup(name) == nil {
			t.Errorf("run does not register --%s", name)
		}
	}
	// run writes nothing, and --host-certs only changes a file init writes.
	if cmd.Flags().Lookup("host-certs") != nil {
		t.Error("run registers --host-certs")
	}
}

// A home with no kumoss.yaml must be told to install, not handed to compose.
func TestRunCmdRefusesAnUninstalledHome(t *testing.T) {
	flags := cli.Flags{Home: home.Home{Root: t.TempDir()}}
	root := &cobra.Command{Use: "kumoss"}
	NewRunCmd(root, &flags)
	root.SetArgs([]string{"run"})
	root.SetOut(&strings.Builder{})

	err := root.Execute()

	if err == nil {
		t.Fatal("an empty home was accepted")
	}
	if !strings.Contains(err.Error(), "kumoss init") {
		t.Errorf("the error does not point at init: %v", err)
	}
}
