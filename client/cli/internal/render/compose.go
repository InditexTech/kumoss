// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"fmt"

	"gopkg.in/yaml.v3"
)

// Compose renders compose.override.yml. The base file points core's config
// volume at src/config.yaml; this re-points it at the generated
// config/config.yaml, which is what makes a config change cost a container
// recreate rather than an image build. The env_file entries need no override.
//
// HostCerts additionally wires the host's CA roots into core and searxng, the
// same block as docker-compose.override.example.yml in the repo.
//
// Compose resolves relative paths against the BASE file (the first -f), not the
// override's own directory, so ConfigPath is relative to src/ and starts with
// ../. Getting it wrong is silent: the targets then differ and compose keeps
// the base mount instead of replacing it.
type Compose struct {
	// Path is where compose.override.yml is written (the home root).
	Path string
	// ConfigPath is the bind-mount source, relative to src/.
	ConfigPath string
	// HostCerts adds the CA wiring to core and searxng. Off by default: that
	// host directory is usually absent.
	HostCerts bool
	// Mounts are the read-only credential mounts for the iac service; compose
	// merges them into the service's existing volume list.
	Mounts []Mount
}

// ContainerConfigPath is where core reads its config. It must match the base
// file's volume target, or compose adds a second mount instead of replacing.
const ContainerConfigPath = "/etc/kumoss/config.yaml"

// hostCADir holds the host's CA roots, overridable with KUMOSS_HOST_CA_DIR.
// The default is where Debian/Ubuntu keep extra roots.
const hostCADir = "${KUMOSS_HOST_CA_DIR:-/usr/local/share/ca-certificates}"

// containerCADir is where that lands in the container, and what KUMOSS_CA_DIR
// points at. Both entrypoints read it.
const containerCADir = "/usr/local/share/ca-certificates/host"

// Write replaces the override wholesale: it is generated, not user state.
func (c *Compose) Write() error {
	out, err := c.Render()
	if err != nil {
		return err
	}
	return writeFile(c.Path, out, 0o644)
}

// Render returns the bytes Write would put on disk, for --dry-run.
func (c *Compose) Render() ([]byte, error) {
	core := map[string]any{
		"volumes": []string{c.ConfigPath + ":" + ContainerConfigPath + ":ro"},
		// Redundant on purpose: the mount already puts the file at the core's
		// default path. It only earns its keep if the core changes that
		// default while this mount target stays put.
		"environment": map[string]string{
			"KUMOSS_CONFIG": ContainerConfigPath,
		},
	}
	doc := map[string]any{
		"services": map[string]any{"core": core},
	}
	if len(c.Mounts) > 0 {
		volumes := make([]string, 0, len(c.Mounts))
		for _, m := range c.Mounts {
			volumes = append(volumes, m.Source+":"+m.Target+":ro")
		}
		// Only iac carries mounts today.
		doc["services"] = map[string]any{
			"core": core,
			"iac":  map[string]any{"volumes": volumes},
		}
	}
	if c.HostCerts {
		// Both services merge the same anchor; core's own volumes entry above
		// is merged, not replaced.
		doc["x-host-ca"] = hostCA()
		services := doc["services"].(map[string]any)
		services["core"] = mergeHostCA(core)
		services["searxng"] = hostCA()
		doc["services"] = services
	}
	out, err := yaml.Marshal(doc)
	if err != nil {
		return nil, fmt.Errorf("marshal compose override: %w", err)
	}
	return out, nil
}

// hostCA is the shared CA block: the roots at build time, since the images
// fetch dependencies over HTTPS, and the same directory mounted at runtime.
func hostCA() map[string]any {
	return map[string]any{
		"build": map[string]any{
			"additional_contexts": map[string]string{"host-certs": hostCADir},
		},
		"environment": []string{"KUMOSS_CA_DIR=" + containerCADir},
		"volumes":     []string{hostCADir + ":" + containerCADir + ":ro"},
	}
}

// mergeHostCA adds the CA fields to core's block rather than replacing it: a
// second mapping under the same service would win outright.
func mergeHostCA(core map[string]any) map[string]any {
	ca := hostCA()
	core["build"] = ca["build"]
	// Compose merges a list, but core's entry is a map and mixing the shapes is
	// a type error — so restate KUMOSS_CONFIG here.
	core["environment"] = []string{
		"KUMOSS_CONFIG=" + ContainerConfigPath,
		"KUMOSS_CA_DIR=" + containerCADir,
	}
	core["volumes"] = append(core["volumes"].([]string), ca["volumes"].([]string)...)
	return core
}
