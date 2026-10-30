// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package render turns the wizard's answers into the generated files: the
// system config.yaml mounted into the core, and the kumoss.yaml state.
package render

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// Config renders config.yaml from the repo's default file plus the answers.
//
// The overlay is done on the decoded YAML map, not on a Go struct, so every key
// the repo's config.yaml carries — including ones the forms do not ask about
// (oidc, orchestration, redis, telemetry, paths, …) — survives into the
// generated file. Only the keys the wizard owns are replaced.
type Config struct {
	// Fetch downloads a repo file at the release tag. Required: the caller (the
	// composition root) injects it, so this package never depends on a concrete
	// downloader. A function, not a fetcher type, so tests can stub it inline.
	Fetch func(ctx context.Context, tag, path string) ([]byte, error)
	// Tag is the release tag to fetch (buildinfo.KumossTag()).
	Tag string
}

// Render fetches the default config.yaml at c.Tag, overlays the answers in s,
// and writes it to path. Missing parent directories are created.
func (c *Config) Render(ctx context.Context, path string, s *state.State) error {
	raw, err := c.Fetch(ctx, c.Tag, "config.yaml")
	if err != nil {
		return err
	}

	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return fmt.Errorf("parse fetched config.yaml: %w", err)
	}
	if doc == nil {
		doc = map[string]any{}
	}

	overlay(doc, s)

	out, err := yaml.Marshal(doc)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, out, 0o644)
}

// overlay replaces the keys the wizard owns with the answers. Everything else
// in doc is left as the repo shipped it.
func overlay(doc map[string]any, s *state.State) {
	doc["llm"] = map[string]any{
		"model":             s.LLM.Model,
		"small_model":       s.LLM.SmallModel,
		"temperature":       s.LLM.Temperature,
		"max_output_tokens": s.LLM.MaxOutputTokens,
		"timeout":           s.LLM.Timeout,
	}
	doc["git"] = map[string]any{
		"provider":     s.Git.Provider,
		"author_name":  s.Git.AuthorName,
		"author_email": s.Git.AuthorEmail,
	}
	doc["storage"] = storageBlock(doc, s)
}

// storageBlock builds storage:, preserving the keys the forms do not own
// (terraform_state_filename, timeouts, presign_expiry_seconds) from the fetched
// file.
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
