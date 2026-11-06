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
// With HostCerts it also wires the corporate CA roots: an x-host-ca anchor
// applies the host-certs build context, the KUMOSS_CA_DIR mount and the env var
// to core and searxng, so both images trust a TLS-inspecting proxy at build and
// runtime. Same block as docker-compose.override.example.yml in the repo.
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
	// HostCerts adds the corporate CA wiring to core and searxng. Off by default:
	// the default host directory does not exist on a normal network.
	HostCerts bool
}

// ContainerConfigPath is where core reads its config inside the container. It
// must match the base file's volume target, or compose adds a second mount
// instead of replacing the first.
const ContainerConfigPath = "/etc/kumoss/config.yaml"

// hostCADir is the host directory holding the CA roots, overridable with
// KUMOSS_HOST_CA_DIR at compose time. The default is the system's extra-roots
// directory, which is where the roots live on Debian/Ubuntu.
const hostCADir = "${KUMOSS_HOST_CA_DIR:-/usr/local/share/ca-certificates}"

// containerCADir is where that directory is mounted inside the container, and
// what KUMOSS_CA_DIR points at. Both entrypoints read it.
const containerCADir = "/usr/local/share/ca-certificates/host"

// Write writes the override. It is a whole-file write, so a hand-edited
// override is replaced: the file is generated, not user state.
func (c *Compose) Write() error {
	core := map[string]any{
		"volumes": []string{c.ConfigPath + ":" + ContainerConfigPath + ":ro"},
		// SystemConfig.load reads this before falling back to its default
		// path, so an explicit value keeps the two in step if the base
		// file's mount ever moves.
		"environment": map[string]string{
			"KUMOSS_CONFIG": ContainerConfigPath,
		},
	}
	doc := map[string]any{
		"services": map[string]any{"core": core},
	}
	if c.HostCerts {
		// Both services merge the same anchor, so compose applies the CA build
		// context and mount to each without repeating them. The core's own
		// volumes entry above is merged, not replaced.
		doc["x-host-ca"] = hostCA()
		doc["services"] = map[string]any{
			"core":    mergeHostCA(core),
			"searxng": hostCA(),
		}
	}
	out, err := yaml.Marshal(doc)
	if err != nil {
		return fmt.Errorf("marshal compose override: %w", err)
	}
	return writeFile(c.Path, out, 0o644)
}

// hostCA is the shared CA block: the roots at build time (the images fetch
// dependencies over HTTPS) and the same directory mounted at runtime, where each
// entrypoint merges it into a trust bundle.
func hostCA() map[string]any {
	return map[string]any{
		"build": map[string]any{
			"additional_contexts": map[string]string{"host-certs": hostCADir},
		},
		"environment": []string{"KUMOSS_CA_DIR=" + containerCADir},
		"volumes":     []string{hostCADir + ":" + containerCADir + ":ro"},
	}
}

// mergeHostCA adds the CA fields to core's own block rather than replacing it:
// core already carries a volumes and an environment entry, and a second mapping
// under the same service would win outright.
func mergeHostCA(core map[string]any) map[string]any {
	ca := hostCA()
	core["build"] = ca["build"]
	// Compose merges environment given as a list; core's own entry is a map, and
	// mixing the two shapes is a type error, so restate KUMOSS_CONFIG here.
	core["environment"] = []string{
		"KUMOSS_CONFIG=" + ContainerConfigPath,
		"KUMOSS_CA_DIR=" + containerCADir,
	}
	core["volumes"] = append(core["volumes"].([]string), ca["volumes"].([]string)...)
	return core
}
