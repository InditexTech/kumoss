// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package home

import (
	"os"
	"path/filepath"
	"strings"
)

// pointerPath is where the chosen home is remembered. It must live OUTSIDE the
// home it points at, otherwise nothing would know where to look first.
func pointerPath() string {
	dir, err := os.UserConfigDir() // ~/.config on Linux, ~/Library/... on macOS
	if err != nil {
		return ""
	}
	return filepath.Join(dir, "kumoss", "home")
}

// readPointer returns the persisted home, or "" when none was ever set.
func readPointer() string {
	p := pointerPath()
	if p == "" {
		return ""
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

// SetPointer remembers root so later invocations resolve it without --home.
// Called only by `kumoss init`.
func SetPointer(root string) error {
	p := pointerPath()
	if p == "" {
		return nil // no config dir: fall back to flag/env only, nothing to persist
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
		return err
	}
	return os.WriteFile(p, []byte(root+"\n"), 0o600)
}

// ClearPointer forgets the persisted home so resolution falls back to
// KUMOSS_HOME, then ~/.kumoss. A missing pointer is not an error.
func ClearPointer() error {
	p := pointerPath()
	if p == "" {
		return nil
	}
	if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}
