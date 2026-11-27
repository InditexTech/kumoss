// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/cli"
	"github.com/spf13/cobra"
)

func TestNoCommandRegistersHome(t *testing.T) {
	var flags cli.Flags
	root := &cobra.Command{Use: "kumoss"}
	NewInitCmd(root, &flags)
	NewRunCmd(root, &flags)
	NewHomeCmd(root, &flags)
	NewConfigCmd(root, &flags)
	NewStatusCmd(root, &flags)
	NewLogsCmd(root, &flags)
	NewDoctorCmd(root, &flags)
	for _, c := range root.Commands() {
		if c.Flags().Lookup("home") != nil {
			t.Errorf("%s still registers --home", c.Name())
		}
	}
	root.SetArgs([]string{"init", "--home", "/tmp/x"})
	root.SetOut(&strings.Builder{})
	root.SetErr(&strings.Builder{})
	if err := root.Execute(); err == nil || !strings.Contains(err.Error(), "unknown flag") {
		t.Errorf("init --home was accepted: %v", err)
	}
}
