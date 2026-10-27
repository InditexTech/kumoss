// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package home

import (
	"os"
	"path/filepath"
	"strings"
)

// Home is the resolved root of the managed directory. It is the only place
// that knows the ~/.kumoss layout; everything else asks for paths here.
type Home struct {
	Root string
}

// Source records why the root resolved the way it did.
type Source int

const (
	SourceFlag Source = iota
	SourceEnv
	SourcePointer
	SourceDefault
)

// FromFlag resolves the home directory. Precedence: --home flag, then
// KUMOSS_HOME, then the pointer file written by `kumoss init`, then ~/.kumoss.
// This is the only reader of KUMOSS_HOME.
func FromFlag(flagHome string) Home {
	h, _ := Resolve(flagHome)
	return h
}

// Resolve is FromFlag plus the Source, for `kumoss home` to explain itself.
func Resolve(flagHome string) (Home, Source) {
	switch {
	case flagHome != "":
		return Home{Root: expand(flagHome)}, SourceFlag
	case os.Getenv("KUMOSS_HOME") != "":
		return Home{Root: expand(os.Getenv("KUMOSS_HOME"))}, SourceEnv
	case readPointer() != "":
		return Home{Root: expand(readPointer())}, SourcePointer
	default:
		return Home{Root: defaultRoot()}, SourceDefault
	}
}

// expand makes a path absolute and resolves a leading ~, so a quoted
// `--home '~/x'` or a relative `--home x` is stored and reported as a real
// path that does not depend on the caller's working directory.
func expand(path string) string {
	switch {
	case path == "~":
		if dir, err := os.UserHomeDir(); err == nil {
			path = dir
		}
	case strings.HasPrefix(path, "~/"):
		if dir, err := os.UserHomeDir(); err == nil {
			path = filepath.Join(dir, path[2:])
		}
	}
	if abs, err := filepath.Abs(path); err == nil {
		return abs
	}
	return filepath.Clean(path)
}

func defaultRoot() string {
	dir, err := os.UserHomeDir()
	if err != nil {
		return ".kumoss"
	}
	return filepath.Join(dir, ".kumoss")
}

// StateFile is ~/.kumoss/kumoss.yaml — the persisted, non-secret state.
func (h Home) StateFile() string { return filepath.Join(h.Root, "kumoss.yaml") }

// SrcDir is the shallow clone of InditexTech/kumoss.
func (h Home) SrcDir() string { return filepath.Join(h.Root, "src") }

// ConfigDir holds the generated system config mounted into the core.
func (h Home) ConfigDir() string { return filepath.Join(h.Root, "config") }

// ConfigYAML is config/config.yaml.
func (h Home) ConfigYAML() string { return filepath.Join(h.ConfigDir(), "config.yaml") }

// ComposeOverride is the generated docker compose override.
func (h Home) ComposeOverride() string { return filepath.Join(h.Root, "compose.override.yml") }

// CoreEnv is src/core/.env.
func (h Home) CoreEnv() string { return filepath.Join(h.SrcDir(), "core", ".env") }

// ServicesDir is src/services/ — one subdir per sidecar.
func (h Home) ServicesDir() string { return filepath.Join(h.SrcDir(), "services") }

// ServiceEnv is src/services/<name>/.env.
func (h Home) ServiceEnv(name string) string {
	return filepath.Join(h.ServicesDir(), name, ".env")
}

// Services needing a generated .env. Hardcoded because the CLI ships without
// the repo, so there is no src/services/ or env.sample to read: these are the
// bundled sidecars plus the search backend. mapping and authz are
// contracts-only and take no .env. Keep in sync when the stack gains a service.
var Services = []string{"iac", "notifications", "searxng"}

// Ensure creates the empty skeleton directories. File contents are written by
// their producers (stack.Clone for src/, render + Write for the rest).
func (h Home) Ensure() error {
	for _, dir := range []string{h.Root, h.SrcDir(), h.ServicesDir(), h.ConfigDir()} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return err
		}
	}
	return nil
}
