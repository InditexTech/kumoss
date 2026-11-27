// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package buildinfo

import (
	"os"
	"regexp"
	"strings"
)

// Version is the CLI version. It is overwritten at build time via
//
//	-ldflags "-X github.com/InditexTech/kumoss/client/cli/internal/buildinfo.Version=v1.2.3"
//
// and stays "dev" for local builds.
var Version = "dev"

// developBranch is where a development build reads the stack from: the compose
// file and config.yaml it downloads have to match the code it was built from,
// and that is develop, not the last release on main.
const developBranch = "develop"

// releaseVersion matches what release-please tags: a semantic version, with an
// optional leading v and an optional pre-release or build suffix. Anything
// else — empty, dev, develop, a bare commit sha — is a development build.
var releaseVersion = regexp.MustCompile(`^v?[0-9]+\.[0-9]+\.[0-9]+([-+].*)?$`)

// KumossTag is the git ref the CLI downloads the stack files from.
//
// A release build pins the tag it was cut with, so the stack always matches
// the binary, and KUMOSS_TAG cannot move it. Any other build follows
// KUMOSS_TAG when set and the develop branch otherwise.
func KumossTag() string {
	if releaseVersion.MatchString(Version) {
		return "v" + strings.TrimPrefix(Version, "v")
	}
	if tag := os.Getenv("KUMOSS_TAG"); tag != "" {
		return tag
	}
	return developBranch
}
