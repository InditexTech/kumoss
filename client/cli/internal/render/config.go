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

// Write fetches the default config.yaml, keeps a verbatim copy at c.Example,
// overlays the answers in s, and writes the result to c.Path.
func (c *Config) Write(ctx context.Context, s *state.State) error {
	raw, err := c.Download.Example(ctx, "config.yaml", c.Example)
	if err != nil {
		return err
	}
	out, err := RenderConfig(raw, s)
	if err != nil {
		return err
	}
	return writeFile(c.Path, out, 0o644)
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
	doc["git"] = map[string]any{
		"provider":     s.Git.Provider,
		"author_name":  s.Git.AuthorName,
		"author_email": s.Git.AuthorEmail,
	}
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
	block["provider"] = s.Storage.Provider
	block["bucket"] = s.Storage.Bucket
	// Empty string is meaningful: repository-declared state. Never a YAML null.
	block["terraform_state_bucket"] = s.Storage.TerraformStateBucket
	if s.Storage.Region != "" {
		block["region"] = s.Storage.Region
	}
	if s.Storage.EndpointURL != "" {
		block["endpoint_url"] = s.Storage.EndpointURL
	}
	if s.Storage.PublicEndpointURL != "" {
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
	return block
}
