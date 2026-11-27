// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package render turns the wizard's answers into the generated files:
// config.yaml, the three .env files and compose.override.yml. One type per
// artifact, sharing one Download.
package render

import (
	"context"
	"fmt"
	"os"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// Config renders config.yaml from the repo's file plus the answers. The overlay
// runs on the decoded YAML map, not a Go struct, so every key the forms never
// ask about (oidc, redis, telemetry…) survives untouched.
type Config struct {
	// Download fetches the repo's config.yaml.
	Download *Download
	// Path is where the rendered config.yaml is written.
	Path string
	// Example keeps the fetched file verbatim: YAML marshalling drops every
	// comment, so this copy is the documentation. Refreshed each run.
	Example string
}

// Write overlays the answers in s onto the existing config.yaml and writes the
// result to c.Path. On a fresh install there is none yet, so it falls back to
// the repo's default, keeping a verbatim copy at c.Example.
func (c *Config) Write(ctx context.Context, s *state.State) error {
	// The file already on disk wins over the shipped default: overlay keeps
	// every key the forms never ask about, so seeding it from the default would
	// revert them — oidc's blank issuer_url turns authentication off.
	raw, err := os.ReadFile(c.Path)
	if err != nil {
		if !os.IsNotExist(err) {
			return err
		}
		if raw, err = c.Download.Example(ctx, "config.yaml", c.Example); err != nil {
			return err
		}
	}
	out, err := RenderConfig(raw, s)
	if err != nil {
		return err
	}
	return writeFile(c.Path, out, 0o644)
}

// WriteConfig writes rendered config.yaml bytes atomically, so `kumoss config`
// does not refetch a file it already has on disk.
func WriteConfig(path string, data []byte) error {
	return writeFile(path, data, 0o644)
}

// RenderConfig is Write without the write, for --dry-run.
func RenderConfig(raw []byte, s *state.State) ([]byte, error) {
	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return nil, fmt.Errorf("parse fetched config.yaml: %w", err)
	}
	if doc == nil {
		doc = map[string]any{}
	}
	overlay(doc, s)
	return yaml.Marshal(doc)
}

// overlay replaces the keys the wizard owns with the answers. Everything else
// in doc is left as the repo shipped it.
func overlay(doc map[string]any, s *state.State) {
	// Merge, not replace: a key the wizard leaves unset must keep its value.
	llm := map[string]any{}
	if existing, ok := doc["llm"].(map[string]any); ok {
		for k, v := range existing {
			llm[k] = v
		}
	}
	llm["model"] = s.LLM.Model
	llm["small_model"] = s.LLM.SmallModel
	// nil means the form never asked (ModeKeep, a stub UI, an older
	// kumoss.yaml), so the fetched value wins. A set pointer wins, zero included.
	if v := s.LLM.Temperature; v != nil {
		llm["temperature"] = *v
	}
	if v := s.LLM.MaxOutputTokens; v != nil {
		llm["max_output_tokens"] = *v
	}
	if v := s.LLM.Timeout; v != nil {
		llm["timeout"] = *v
	}
	doc["llm"] = llm
	// Merge too: pat_user_env and pat_token_env name the credentials, and
	// replacing the block would point the core back at GIT_USER/GIT_TOKEN.
	git := map[string]any{}
	if existing, ok := doc["git"].(map[string]any); ok {
		for k, v := range existing {
			git[k] = v
		}
	}
	git["provider"] = s.Git.Provider
	git["author_name"] = s.Git.AuthorName
	git["author_email"] = s.Git.AuthorEmail
	doc["git"] = git
	doc["storage"] = storageBlock(doc, s)
	doc["services"] = servicesBlock(doc, s)
}

// storageBlock preserves the keys the forms do not own (timeouts,
// presign_expiry_seconds, terraform_state_filename).
func storageBlock(doc map[string]any, s *state.State) map[string]any {
	block := map[string]any{}
	if existing, ok := doc["storage"].(map[string]any); ok {
		for k, v := range existing {
			block[k] = v
		}
	}
	// The CLI's model discriminator is not a config key: a kumoss.yaml written
	// before it existed, or one edited by hand, carries none, and an empty
	// provider here would overwrite the fetched value with nothing. Leaving
	// the key out keeps the file's own provider, the same as an unset knob.
	if s.Storage.Provider != "" {
		block["provider"] = s.Storage.Provider
	}
	if s.Storage.Bucket != "" {
		block["bucket"] = s.Storage.Bucket
	}
	// Empty string is meaningful: a repo-declared backend, kept on Azure. Never
	// a YAML null.
	if s.Storage.Provider != "" {
		block["terraform_state_bucket"] = s.Storage.TerraformStateBucket
	}
	if s.Storage.Region != "" {
		block["region"] = s.Storage.Region
	}
	// Azure's endpoint is built from the account name, not typed: an endpoint
	// the wizard did not derive (a reconfigure, a hand-edited state) must not
	// reach the file.
	azure := s.Storage.Model == "external_azure"
	if s.Storage.EndpointURL != "" && !azure {
		block["endpoint_url"] = s.Storage.EndpointURL
	}
	if s.Storage.PublicEndpointURL != "" && !azure {
		block["public_endpoint_url"] = s.Storage.PublicEndpointURL
	}
	return block
}

// servicesBlock sets notifications.enabled and preserves every other sidecar
// key as the repo ships it.
func servicesBlock(doc map[string]any, s *state.State) map[string]any {
	block := map[string]any{}
	if existing, ok := doc["services"].(map[string]any); ok {
		for k, v := range existing {
			block[k] = v
		}
	}
	notifications := map[string]any{}
	if existing, ok := block["notifications"].(map[string]any); ok {
		for k, v := range existing {
			notifications[k] = v
		}
	}
	notifications["enabled"] = s.Notifications.Enabled
	block["notifications"] = notifications
	mapping := map[string]any{}
	if existing, ok := block["mapping"].(map[string]any); ok {
		for k, v := range existing {
			mapping[k] = v
		}
	}
	// Only a turned-on answer is written: mapping defaults to on in the shipped
	// config.yaml, so a state loaded before this section existed records false
	// and would silently switch a hand-enabled service off.
	if s.Mapping.Enabled {
		mapping["enabled"] = true
	}
	block["mapping"] = mapping
	return block
}
