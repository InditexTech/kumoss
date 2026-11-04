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
// src/ — is src/config.yaml. The generated config lives at config/config.yaml in
// the home root, so the override re-points that mount and sets KUMOSS_CONFIG to
// the same path inside the container. The env_file entries need no override:
// they already resolve to src/core/.env and src/services/<name>/.env.
//
// The CLI runs compose with an explicit -f list, and compose resolves every
// relative path against the BASE file (the first -f), not against the override's
// own directory. So ConfigPath is relative to src/ and starts with ../. Getting
// this wrong is silent: the two entries then resolve to different targets, so
// compose keeps the base mount and appends nothing.
//
// Mounting config.yaml read-only is what makes a config change cheap: editing it
// needs only a container recreate, never `docker compose build core`.
type Compose struct {
	// Path is where compose.override.yml is written (the home root).
	Path string
	// ConfigPath is the bind-mount source, relative to the base compose file's
	// directory (src/). "../config/config.yaml" by default.
	ConfigPath string
}

// ContainerConfigPath is where core reads its config inside the container. It
// must match the base file's volume target, or compose adds a second mount
// instead of replacing the first.
const ContainerConfigPath = "/etc/kumoss/config.yaml"

// Write writes the override. It is a whole-file write, so a hand-edited
// override is replaced: the file is generated, not user state.
func (c *Compose) Write() error {
	doc := map[string]any{
		"services": map[string]any{
			"core": map[string]any{
				"volumes": []string{c.ConfigPath + ":" + ContainerConfigPath + ":ro"},
				// SystemConfig.load reads this before falling back to its default
				// path, so an explicit value keeps the two in step if the base
				// file's mount ever moves.
				"environment": map[string]string{
					"KUMOSS_CONFIG": ContainerConfigPath,
				},
			},
		},
	}
	out, err := yaml.Marshal(doc)
	if err != nil {
		return fmt.Errorf("marshal compose override: %w", err)
	}
	return writeFile(c.Path, out, 0o644)
}
