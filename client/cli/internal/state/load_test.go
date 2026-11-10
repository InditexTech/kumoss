// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Save/Load round-trips the persisted fields and never carries a secret.
func TestSaveLoadRoundTripWithoutSecrets(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kumoss.yaml")
	s := &State{
		SchemaVersion: 1,
		LLM:           LLM{Model: "anthropic/claude", SmallModel: "anthropic/haiku", Temperature: ptr(0.2), MaxOutputTokens: ptr(16000), Timeout: ptr(300.0)},
		Git:           Git{Provider: "GITHUB", AuthorName: "Bot", AuthorEmail: "bot@example.invalid"},
		Storage:       Storage{Provider: "S3", Bucket: "artifacts", TerraformStateBucket: "", Region: "eu-west-1"},
		Secrets:       Secrets{IACToken: "must-not-be-saved", NotificationsToken: "nor-this"},
		Cloud:         Cloud{AWS: &AWSAuth{AccessKey: "also-secret"}},
	}
	if err := Save(path, s); err != nil {
		t.Fatalf("Save: %v", err)
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	for _, secret := range []string{"must-not-be-saved", "nor-this", "also-secret"} {
		if strings.Contains(string(raw), secret) {
			t.Errorf("kumoss.yaml carries the secret %q", secret)
		}
	}

	got, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got.SchemaVersion != 1 || got.LLM.Model != "anthropic/claude" || got.Git.Provider != "GITHUB" {
		t.Errorf("round-trip lost fields: %+v", got)
	}
	if got.Storage.Bucket != "artifacts" || got.Storage.Region != "eu-west-1" {
		t.Errorf("storage lost: %+v", got.Storage)
	}
	// yaml:"-" fields never survive, by design.
	if got.Secrets.IACToken != "" || got.Cloud.AWS != nil {
		t.Error("a yaml:\"-\" field was persisted")
	}
}

// A partial file loads with zero values; the forms re-fill the gaps.
func TestLoadToleratesMissingKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kumoss.yaml")
	if err := os.WriteFile(path, []byte("schema_version: 1\nllm:\n  model: keep/me\n"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	s, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if s.LLM.Model != "keep/me" {
		t.Errorf("model = %q", s.LLM.Model)
	}
	if s.Storage.Bucket != "" {
		t.Errorf("missing storage should be zero, got %q", s.Storage.Bucket)
	}
}

// A wrong type is a real error: it means the file is not ours.
func TestLoadRejectsWrongTypes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kumoss.yaml")
	if err := os.WriteFile(path, []byte("llm:\n  temperature: hot\n"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	if _, err := Load(path); err == nil {
		t.Error("Load accepted a non-numeric temperature")
	}
}

func TestStateFileExist(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "kumoss.yaml")

	if exists, err := StateFileExist(path); err != nil || exists {
		t.Errorf("missing file: exists=%v err=%v, want false nil", exists, err)
	}

	if err := os.WriteFile(path, []byte("schema_version: 1\n"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	if exists, err := StateFileExist(path); err != nil || !exists {
		t.Errorf("present file: exists=%v err=%v, want true nil", exists, err)
	}

	// A directory named kumoss.yaml is not a state file.
	dirPath := filepath.Join(dir, "dir.yaml")
	if err := os.Mkdir(dirPath, 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if exists, err := StateFileExist(dirPath); err != nil || exists {
		t.Errorf("directory: exists=%v err=%v, want false nil", exists, err)
	}
}

// Save writes 0600: the file names this install's buckets and providers.
func TestSaveUsesOwnerOnlyPermissions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kumoss.yaml")
	if err := Save(path, &State{SchemaVersion: 1}); err != nil {
		t.Fatalf("Save: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if perm := info.Mode().Perm(); perm != 0o600 {
		t.Errorf("mode = %o, want 600", perm)
	}
}

// ptr is the address of a literal, for the optional tuning knobs.
func ptr[T any](v T) *T { return &v }
