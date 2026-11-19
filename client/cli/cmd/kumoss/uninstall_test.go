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
)

// runUninstall drives the command with a fake home. A home with no
// src/docker-compose.yml skips the compose step, so no daemon is needed.
func runUninstall(t *testing.T, root string, purge bool, answer string) string {
	t.Helper()
	var out bytes.Buffer
	c := &cobra.Command{Use: "uninstall", SilenceUsage: true, SilenceErrors: true}
	c.SetOut(&out)
	c.SetIn(strings.NewReader(answer))
	sub := NewUninstallCmd(c, &cli.Flags{Home: home.Home{Root: root}})
	if purge {
		if err := sub.Flags().Set("purge", "true"); err != nil {
			t.Fatal(err)
		}
	}
	if err := sub.RunE(sub, nil); err != nil {
		t.Fatal(err)
	}
	return out.String()
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// markManaged writes the kumoss.yaml that init leaves behind, so the root counts
// as a Kumoss home. Content is irrelevant: uninstall only stats it.
func markManaged(t *testing.T, root string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, "kumoss.yaml"), []byte("schema_version: 1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestUninstallAsksBeforeDeleting(t *testing.T) {
	root := t.TempDir()
	markManaged(t, root)
	if out := runUninstall(t, root, false, "n\n"); !strings.Contains(out, "Aborted") {
		t.Errorf("output = %q, want an abort notice", out)
	}
	if !exists(root) {
		t.Error("home deleted after a no")
	}
}

// A closed or piped stdin must never read as consent.
func TestUninstallTreatsEOFAsNo(t *testing.T) {
	root := t.TempDir()
	markManaged(t, root)
	runUninstall(t, root, false, "")
	if !exists(root) {
		t.Error("home deleted without an answer")
	}
}

func TestUninstallPurgeRemovesTheHome(t *testing.T) {
	root := t.TempDir()
	markManaged(t, root)
	runUninstall(t, root, true, "")
	if exists(root) {
		t.Error("home still exists after --purge")
	}
}

// A stray --home must not delete a directory Kumoss never created, even with
// --purge: no kumoss.yaml means it is not a home.
func TestUninstallRefusesAnUnmanagedDirectory(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "notes.txt"), []byte("keep me"), 0o600); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	c := &cobra.Command{Use: "uninstall", SilenceUsage: true, SilenceErrors: true}
	c.SetOut(&out)
	sub := NewUninstallCmd(c, &cli.Flags{Home: home.Home{Root: root}})
	if err := sub.Flags().Set("purge", "true"); err != nil {
		t.Fatal(err)
	}
	err := sub.RunE(sub, nil)
	if err == nil || !strings.Contains(err.Error(), "not a Kumoss home") {
		t.Errorf("err = %v, want a refusal", err)
	}
	if !exists(filepath.Join(root, "notes.txt")) {
		t.Error("unmanaged directory was deleted")
	}
}
