// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package home

import (
	"os"
	"path/filepath"
	"strings"
)

// Home is the resolved root, and the only place that knows the ~/.kumoss
// layout; everything else asks for paths here.
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

// FromFlag resolves the home: --home, then KUMOSS_HOME, then the pointer file,
// then ~/.kumoss. The only reader of KUMOSS_HOME.
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
// `--home '~/x'` does not depend on the caller's working directory.
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

// SrcDir is src/, which holds the downloaded compose project file.
func (h Home) SrcDir() string { return filepath.Join(h.Root, "src") }

// ConfigDir holds the generated system config mounted into the core.
func (h Home) ConfigDir() string { return filepath.Join(h.Root, "config") }

// ConfigYAML is config/config.yaml.
func (h Home) ConfigYAML() string { return filepath.Join(h.ConfigDir(), "config.yaml") }

// ConfigExample keeps the repo's config.yaml verbatim, with the comments the
// generated file loses.
func (h Home) ConfigExample() string { return h.ConfigYAML() + ".example" }

// ComposeOverride is the generated docker compose override.
func (h Home) ComposeOverride() string { return filepath.Join(h.Root, "compose.override.yml") }

// ComposeFile is src/docker-compose.yml. It sits in src/ so its own ./core/.env
// and ./services/<name>/.env paths resolve to the generated files.
func (h Home) ComposeFile() string { return filepath.Join(h.SrcDir(), "docker-compose.yml") }

// CoreEnv is src/core/.env.
func (h Home) CoreEnv() string { return filepath.Join(h.SrcDir(), "core", ".env") }

// CoreDir is src/core/ — the core's env file lives here.
func (h Home) CoreDir() string { return filepath.Join(h.SrcDir(), "core") }

// ServicesDir is src/services/ — one subdir per sidecar.
func (h Home) ServicesDir(service string) string {
	return filepath.Join(h.SrcDir(), "services", service)
}

// ServiceEnv is src/services/<name>/.env.
func (h Home) ServiceEnv(service string) string {
	return filepath.Join(h.ServicesDir(service), ".env")
}

// Services are the directories created under src/services/. Hardcoded: the CLI
// ships without the repo, so there is no listing to read. Keep in sync when the
// stack gains a service. Only iac and notifications get a generated .env;
// searxng exists for layout parity and stays empty.
var Services = []string{"iac", "notifications", "searxng"}

// Ensure creates the skeleton; the producers write the contents.
func (h Home) Ensure() error {
	dirs := []string{h.Root, h.SrcDir(), h.CoreDir(), h.ConfigDir()}
	for _, name := range Services {
		dirs = append(dirs, h.ServicesDir(name))
	}
	for _, dir := range dirs {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return err
		}
	}
	return nil
}
