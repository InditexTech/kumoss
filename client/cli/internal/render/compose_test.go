// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

func TestComposeOverrideRemapsTheConfigVolume(t *testing.T) {
	path := filepath.Join(t.TempDir(), "compose.override.yml")
	c := &Compose{Path: path, ConfigPath: "../config/config.yaml"}
	if err := c.Write(); err != nil {
		t.Fatalf("Render: %v", err)
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("parse: %v", err)
	}

	core := doc["services"].(map[string]any)["core"].(map[string]any)
	volumes := core["volumes"].([]any)
	if len(volumes) != 1 {
		t.Fatalf("volumes = %v, want one entry", volumes)
	}
	// The container target must match the base file's, or compose adds a second
	// mount instead of replacing the first.
	want := "../config/config.yaml:/etc/kumoss/config.yaml:ro"
	if volumes[0] != want {
		t.Errorf("volume = %v, want %q", volumes[0], want)
	}
}

func TestDownloadSave(t *testing.T) {
	dst := filepath.Join(t.TempDir(), "src", "docker-compose.yml")
	d := &Download{Fetch: stubFetch("services: {}\n"), Tag: "v1.0.0"}

	// stubFetch only answers config.yaml, so point it at that path.
	if err := d.Save(context.Background(), "config.yaml", dst); err != nil {
		t.Fatalf("Save: %v", err)
	}
	raw, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if !strings.Contains(string(raw), "services") {
		t.Errorf("saved bytes = %q", raw)
	}
}

func TestDownloadSaveCreatesParent(t *testing.T) {
	// The compose file lands in src/, which Ensure created — but Save must not
	// assume it, so it creates the parent itself.
	dst := filepath.Join(t.TempDir(), "a", "b", "c.yml")
	d := &Download{Fetch: stubFetch("x: 1\n"), Tag: "v1.0.0"}
	if err := d.Save(context.Background(), "config.yaml", dst); err != nil {
		t.Fatalf("Save: %v", err)
	}
	if _, err := os.Stat(dst); err != nil {
		t.Errorf("file not written: %v", err)
	}
}
