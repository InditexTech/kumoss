// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package buildinfo

import "testing"

// A release build pins its own version; a dev build follows KUMOSS_TAG, then
// main.
func TestKumossTag(t *testing.T) {
	old := Version
	t.Cleanup(func() { Version = old })

	// Release build: the tag is the version, with exactly one leading v.
	Version = "1.2.3"
	t.Setenv("KUMOSS_TAG", "ignored")
	if got := KumossTag(); got != "v1.2.3" {
		t.Errorf("release = %q, want v1.2.3", got)
	}
	Version = "v1.2.3"
	if got := KumossTag(); got != "v1.2.3" {
		t.Errorf("already-prefixed = %q, want v1.2.3", got)
	}

	// Dev build: KUMOSS_TAG, then main.
	Version = "dev"
	t.Setenv("KUMOSS_TAG", "v9.9.9")
	if got := KumossTag(); got != "v9.9.9" {
		t.Errorf("dev with KUMOSS_TAG = %q", got)
	}
	t.Setenv("KUMOSS_TAG", "")
	if got := KumossTag(); got != "main" {
		t.Errorf("dev without KUMOSS_TAG = %q, want main", got)
	}
}
