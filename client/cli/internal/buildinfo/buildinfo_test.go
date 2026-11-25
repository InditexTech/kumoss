// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package buildinfo

import "testing"

// A release build pins its own version; anything else is a development build
// and follows KUMOSS_TAG, then the develop branch.
func TestKumossTagReleaseBuilds(t *testing.T) {
	old := Version
	t.Cleanup(func() { Version = old })
	t.Setenv("KUMOSS_TAG", "ignored")

	for version, want := range map[string]string{
		"1.2.3":      "v1.2.3",
		"v1.2.3":     "v1.2.3",
		"0.1.0":      "v0.1.0",
		"1.2.3-rc.1": "v1.2.3-rc.1",
		"v2.0.0+a1":  "v2.0.0+a1",
	} {
		Version = version
		if got := KumossTag(); got != want {
			t.Errorf("Version %q = %q, want %q", version, got, want)
		}
	}
}

// Everything that is not a release version is a development build. The old
// rule only knew the literal string dev, so a version of develop became the
// ref vdevelop, which does not exist.
func TestKumossTagDevelopmentBuilds(t *testing.T) {
	old := Version
	t.Cleanup(func() { Version = old })
	t.Setenv("KUMOSS_TAG", "")

	for _, version := range []string{
		"", "dev", "develop", "DEV", "dev-20261125", "snapshot",
		"ab04312", "1.2", "v1", "main",
	} {
		Version = version
		if got := KumossTag(); got != "develop" {
			t.Errorf("Version %q = %q, want develop", version, got)
		}
	}
}

// KUMOSS_TAG is the escape hatch for a development build, and is ignored by a
// release build, which must fetch the stack it was cut with.
func TestKumossTagHonoursTheEnvOverrideOnDevBuildsOnly(t *testing.T) {
	old := Version
	t.Cleanup(func() { Version = old })

	t.Setenv("KUMOSS_TAG", "v9.9.9")
	Version = "dev"
	if got := KumossTag(); got != "v9.9.9" {
		t.Errorf("dev with KUMOSS_TAG = %q, want v9.9.9", got)
	}
	Version = ""
	if got := KumossTag(); got != "v9.9.9" {
		t.Errorf("empty with KUMOSS_TAG = %q, want v9.9.9", got)
	}
	Version = "1.2.3"
	if got := KumossTag(); got != "v1.2.3" {
		t.Errorf("release with KUMOSS_TAG = %q, want v1.2.3", got)
	}
}
