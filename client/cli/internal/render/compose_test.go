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

func TestComposeOverrideHostCerts(t *testing.T) {
	path := filepath.Join(t.TempDir(), "compose.override.yml")
	c := &Compose{Path: path, ConfigPath: "../config/config.yaml", HostCerts: true}
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

	// core keeps its config remap and gains the CA mount; losing the first
	// would silently unconfigure it.
	core := doc["services"].(map[string]any)["core"].(map[string]any)
	volumes := core["volumes"].([]any)
	if len(volumes) != 2 {
		t.Fatalf("core volumes = %v, want config plus CA", volumes)
	}
	if volumes[0] != "../config/config.yaml:/etc/kumoss/config.yaml:ro" {
		t.Errorf("config volume lost: %v", volumes[0])
	}
	if volumes[1] != hostCADir+":"+containerCADir+":ro" {
		t.Errorf("CA volume = %v", volumes[1])
	}
	env := core["environment"].([]any)
	if len(env) != 2 || env[0] != "KUMOSS_CONFIG="+ContainerConfigPath || env[1] != "KUMOSS_CA_DIR="+containerCADir {
		t.Errorf("core environment = %v", env)
	}
	build := core["build"].(map[string]any)["additional_contexts"].(map[string]any)
	if build["host-certs"] != hostCADir {
		t.Errorf("host-certs context = %v", build)
	}

	// searxng only needs the CA wiring.
	searxng := doc["services"].(map[string]any)["searxng"].(map[string]any)
	if got := searxng["volumes"].([]any); len(got) != 1 || got[0] != hostCADir+":"+containerCADir+":ro" {
		t.Errorf("searxng volumes = %v", got)
	}
}

// Without the flag the override must not change: that CA directory is absent on
// a normal network, and mounting it would break the stack.
func TestComposeOverrideOmitsHostCertsByDefault(t *testing.T) {
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
	if _, ok := doc["x-host-ca"]; ok {
		t.Error("x-host-ca present without --host-certs")
	}
	if _, ok := doc["services"].(map[string]any)["searxng"]; ok {
		t.Error("searxng override present without --host-certs")
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
