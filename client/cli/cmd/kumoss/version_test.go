// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"bytes"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

// Both the CLI version and the stack tag, on one line: a mismatch needs both.
func TestVersionPrintsBothVersions(t *testing.T) {
	oldVersion := buildinfo.Version
	t.Cleanup(func() { buildinfo.Version = oldVersion })
	buildinfo.Version = "1.2.3"

	var flags cli.Flags
	root := &cobra.Command{Use: "kumoss"}
	NewVersionCmd(root, &flags)

	var out bytes.Buffer
	root.SetOut(&out)
	root.SetArgs([]string{"version"})
	if err := root.Execute(); err != nil {
		t.Fatalf("version: %v", err)
	}

	got := out.String()
	if !strings.Contains(got, "kumoss 1.2.3") {
		t.Errorf("output missing the CLI version: %q", got)
	}
	if !strings.Contains(got, "stack v1.2.3") {
		t.Errorf("output missing the stack tag: %q", got)
	}
}
