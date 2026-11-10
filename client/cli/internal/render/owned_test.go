// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// env.sample ships a dev token per service. A fresh install must not keep it,
// and an unset key must come out empty rather than take the placeholder.
func TestOwnedKeysShadowTheSampleValues(t *testing.T) {
	sample := &Sample{Vars: []Var{
		{Key: "KUMOSS_IAC_TOKEN", Value: "dev-iac-token"},
		{Key: "SLACK_WEBHOOK_URL", Value: "https://hooks.example/dev"},
		{Key: "GIT_TOKEN", Value: "sample-token"},
	}}
	s := &state.State{Secrets: state.Secrets{IACToken: "abc123"}}
	vars := resolveSample(sample, (&Env{}).owned(s), nil)
	if vars["KUMOSS_IAC_TOKEN"] != "abc123" {
		t.Errorf("IAC token = %q, want the generated one", vars["KUMOSS_IAC_TOKEN"])
	}
	if vars["SLACK_WEBHOOK_URL"] != "" {
		t.Errorf("SLACK_WEBHOOK_URL = %q, want empty when notifications are off", vars["SLACK_WEBHOOK_URL"])
	}
	if vars["GIT_TOKEN"] != "" {
		t.Errorf("GIT_TOKEN = %q, want empty when the wizard did not collect one", vars["GIT_TOKEN"])
	}
}

// No temp file left behind, the mode survives the rename, and an existing file
// is replaced rather than appended to.
func TestWriteFileReplacesAtomically(t *testing.T) {
	path := filepath.Join(t.TempDir(), "core", ".env")
	if err := writeFile(path, []byte("A=1\n"), 0o600); err != nil {
		t.Fatalf("first write: %v", err)
	}
	if err := writeFile(path, []byte("B=2\n"), 0o600); err != nil {
		t.Fatalf("second write: %v", err)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "B=2\n" {
		t.Errorf("content = %q", got)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("mode = %v, want 0600", info.Mode().Perm())
	}
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Errorf("leftover temp files: %v", entries)
	}
}
