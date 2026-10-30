// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"fmt"

	"gopkg.in/yaml.v3"
)

// Compose renders compose.override.yml. The downloaded docker-compose.yml points
// core's config volume at ./config.yaml, which — relative to the compose file in
// src/ — is src/config.yaml. The generated config lives at config/config.yaml,
// one level up, so the override re-points that mount. The env_file entries need
// no override: they already resolve to src/core/.env and src/services/<name>/.env.
//
// Compose resolves every relative path against the base file (the first -f), not
// the override, so the path here is relative to src/, hence the leading ../.
type Compose struct {
	// Path is where compose.override.yml is written (the home root).
	Path string
	// ConfigPath is the bind-mount source, relative to the compose file's
	// directory (src/). "../config/config.yaml" by default.
	ConfigPath string
}

// Write writes the override. It is a whole-file write, so a hand-edited
// override is replaced: the file is generated, not user state.
func (c *Compose) Write() error {
	doc := map[string]any{
		"services": map[string]any{
			"core": map[string]any{
				// The mount path must match the base file's for compose to merge
				// the entry by target instead of adding a second mount.
				"volumes": []string{c.ConfigPath + ":/etc/kumoss/config.yaml:ro"},
			},
		},
	}
	out, err := yaml.Marshal(doc)
	if err != nil {
		return fmt.Errorf("marshal compose override: %w", err)
	}
	return writeFile(c.Path, out, 0o644)
}
