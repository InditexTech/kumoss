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

// expand resolves a leading ~ so a quoted `--home '~/x'` is stored and reported
// as a real path, matching the shell's own expansion.
func expand(path string) string {
	if path == "~" || strings.HasPrefix(path, "~/") {
		if dir, err := os.UserHomeDir(); err == nil {
			return filepath.Join(dir, strings.TrimPrefix(strings.TrimPrefix(path, "~"), "/"))
		}
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

// ServiceEnv is src/services/<name>/.env.
func (h Home) ServiceEnv(name string) string {
	return filepath.Join(h.SrcDir(), "services", name, ".env")
}

// Ensure creates the empty skeleton directories. File contents are written by
// their producers (stack.Clone for src/, render + Write for the rest).
func (h Home) Ensure() error {
	for _, dir := range []string{h.Root, h.SrcDir(), h.ConfigDir()} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return err
		}
	}
	return nil
}
