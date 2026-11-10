// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package home

import (
	"os"
	"path/filepath"
	"testing"
)

// isolate keeps the pointer file out of the real ~/.config.
func isolate(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(dir, ".config"))
	t.Setenv("KUMOSS_HOME", "")
	return dir
}

// The layout is the contract with the compose file.
func TestLayout(t *testing.T) {
	h := Home{Root: "/h"}
	cases := map[string]string{
		h.StateFile():       "/h/kumoss.yaml",
		h.SrcDir():          "/h/src",
		h.ComposeFile():     "/h/src/docker-compose.yml",
		h.CoreEnv():         "/h/src/core/.env",
		h.CoreDir():         "/h/src/core",
		h.ConfigYAML():      "/h/config/config.yaml",
		h.ConfigExample():   "/h/config/config.yaml.example",
		h.ComposeOverride(): "/h/compose.override.yml",
		h.ServiceEnv("iac"): "/h/src/services/iac/.env",
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("path = %q, want %q", got, want)
		}
	}
}

// Precedence: --home beats KUMOSS_HOME beats the pointer beats the default.
func TestResolvePrecedence(t *testing.T) {
	dir := isolate(t)

	// Default, with no flag, no env and no pointer.
	h, src := Resolve("")
	if src != SourceDefault || h.Root != filepath.Join(dir, ".kumoss") {
		t.Errorf("default: %q %v", h.Root, src)
	}

	// The pointer wins over the default.
	if err := SetPointer("/from/pointer"); err != nil {
		t.Fatalf("SetPointer: %v", err)
	}
	h, src = Resolve("")
	if src != SourcePointer || h.Root != "/from/pointer" {
		t.Errorf("pointer: %q %v", h.Root, src)
	}

	// KUMOSS_HOME wins over the pointer.
	t.Setenv("KUMOSS_HOME", "/from/env")
	h, src = Resolve("")
	if src != SourceEnv || h.Root != "/from/env" {
		t.Errorf("env: %q %v", h.Root, src)
	}

	// --home wins over everything.
	h, src = Resolve("/from/flag")
	if src != SourceFlag || h.Root != "/from/flag" {
		t.Errorf("flag: %q %v", h.Root, src)
	}
}

// A quoted ~ or a relative path must not depend on the caller's cwd.
func TestExpandResolvesTildeAndRelative(t *testing.T) {
	dir := isolate(t)

	if got := expand("~/x"); got != filepath.Join(dir, "x") {
		t.Errorf("~/x = %q", got)
	}
	if got := expand("~"); got != dir {
		t.Errorf("~ = %q", got)
	}
	if got := expand("rel"); !filepath.IsAbs(got) {
		t.Errorf("rel = %q, want absolute", got)
	}
}

// SetPointer/ClearPointer round-trips; clearing an absent pointer is fine.
func TestPointerRoundTrip(t *testing.T) {
	isolate(t)

	if err := SetPointer("/chosen/home"); err != nil {
		t.Fatalf("SetPointer: %v", err)
	}
	if got := readPointer(); got != "/chosen/home" {
		t.Errorf("readPointer = %q", got)
	}
	if err := ClearPointer(); err != nil {
		t.Fatalf("ClearPointer: %v", err)
	}
	if got := readPointer(); got != "" {
		t.Errorf("pointer survived the clear: %q", got)
	}
	// Clearing again is a no-op, not a failure.
	if err := ClearPointer(); err != nil {
		t.Errorf("second ClearPointer: %v", err)
	}
}

// The pointer lives outside the home it points at.
func TestPointerLivesOutsideTheHome(t *testing.T) {
	isolate(t)
	p := pointerPath()
	if p == "" {
		t.Fatal("pointerPath is empty")
	}
	if filepath.Dir(filepath.Dir(p)) != os.Getenv("XDG_CONFIG_HOME") {
		t.Errorf("pointer at %q, want under %s", p, os.Getenv("XDG_CONFIG_HOME"))
	}
}

// Ensure creates one directory per service, and is idempotent.
func TestEnsureCreatesTheSkeleton(t *testing.T) {
	h := Home{Root: filepath.Join(t.TempDir(), "root")}
	for i := 0; i < 2; i++ {
		if err := h.Ensure(); err != nil {
			t.Fatalf("Ensure run %d: %v", i, err)
		}
	}
	for _, dir := range []string{h.Root, h.SrcDir(), h.CoreDir(), h.ConfigDir()} {
		info, err := os.Stat(dir)
		if err != nil {
			t.Errorf("%s not created: %v", dir, err)
			continue
		}
		if !info.IsDir() {
			t.Errorf("%s is not a directory", dir)
		}
	}
	for _, name := range Services {
		if _, err := os.Stat(h.ServicesDir(name)); err != nil {
			t.Errorf("service dir %s not created: %v", name, err)
		}
	}
}
