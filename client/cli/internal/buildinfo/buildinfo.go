// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package buildinfo

import (
	"os"
	"strings"
)

// Version is the CLI version. It is overwritten at build time via
//
//	-ldflags "-X github.com/InditexTech/kumoss/client/cli/internal/buildinfo.Version=v1.2.3"
//
// and stays "dev" for local builds.
var Version = "dev"

func KumossTag() string {
	if Version != "" && Version != "dev" {
		return "v" + strings.TrimPrefix(Version, "v")
	}
	if tag := os.Getenv("KUMOSS_TAG"); tag != "" {
		return tag
	}
	return "main"
}
