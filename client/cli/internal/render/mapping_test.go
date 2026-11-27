// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// The mapping sidecar reads its own file, so the prefix the form collected has
// to land there and nowhere else.
func TestMappingEnvCarriesThePrefix(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{
		Mapping: state.Mapping{Enabled: true, Prefix: "https://github.com/my-org"},
		Secrets: state.Secrets{MappingToken: "mapping-token"},
	}
	e := &Env{Samples: &Samples{
		Mapping: ParseSample("KUMOSS_MAPPING_TOKEN=\nMAPPING_PREFIX_IDENTIFIER=\nLOG_LEVEL=INFO\n"),
	}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}

	mapping := ReadEnv(p.Mapping)
	if mapping["KUMOSS_MAPPING_TOKEN"] != "mapping-token" {
		t.Errorf("KUMOSS_MAPPING_TOKEN = %q, want the generated one", mapping["KUMOSS_MAPPING_TOKEN"])
	}
	if mapping["MAPPING_PREFIX_IDENTIFIER"] != "https://github.com/my-org" {
		t.Errorf("MAPPING_PREFIX_IDENTIFIER = %q, want the answered prefix", mapping["MAPPING_PREFIX_IDENTIFIER"])
	}
	// The sample's LOG_LEVEL survives: the wizard never asks for it.
	if mapping["LOG_LEVEL"] != "INFO" {
		t.Errorf("LOG_LEVEL = %q, want the sample default", mapping["LOG_LEVEL"])
	}
	if got := ReadEnv(p.Core)["MAPPING_PREFIX_IDENTIFIER"]; got != "" {
		t.Errorf("core/.env carries the mapping prefix (%q); only the sidecar reads it", got)
	}
}

// An empty prefix is a supported setup (full URLs only), not a missing value:
// it must not take the sample's placeholder.
func TestMappingEnvKeepsABlankPrefix(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{Mapping: state.Mapping{Enabled: true}}
	e := &Env{Samples: &Samples{Mapping: ParseSample("MAPPING_PREFIX_IDENTIFIER=https://example.test/\n")}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := ReadEnv(p.Mapping)["MAPPING_PREFIX_IDENTIFIER"]; got != "" {
		t.Errorf("MAPPING_PREFIX_IDENTIFIER = %q, want blank", got)
	}
}

// Langfuse refuses a pair that is not the project's, so the core and
// langfuse-web must read the same two values.
func TestLangfusePairReachesBothFiles(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{Secrets: state.Secrets{LangfusePublicKey: "pk-lf-mine", LangfuseSecretKey: "sk-lf-mine"}}
	e := &Env{Samples: &Samples{Core: ParseSample("LANGFUSE_PUBLIC_KEY=pk-lf-kumoss-dev\nLANGFUSE_SECRET_KEY=sk-lf-kumoss-dev\n")}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}

	core := ReadEnv(p.Core)
	if core["LANGFUSE_PUBLIC_KEY"] != "pk-lf-mine" || core["LANGFUSE_SECRET_KEY"] != "sk-lf-mine" {
		t.Errorf("core/.env pair = %q/%q, want the answered one", core["LANGFUSE_PUBLIC_KEY"], core["LANGFUSE_SECRET_KEY"])
	}

	path := filepath.Join(t.TempDir(), "langfuse.env")
	if err := WriteLangfuseEnv(path, s); err != nil {
		t.Fatalf("WriteLangfuseEnv: %v", err)
	}
	pair := ReadEnv(path)
	if pair["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"] != "pk-lf-mine" || pair["LANGFUSE_INIT_PROJECT_SECRET_KEY"] != "sk-lf-mine" {
		t.Errorf("langfuse.env pair = %q/%q, want the answered one", pair["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"], pair["LANGFUSE_INIT_PROJECT_SECRET_KEY"])
	}
	if info, err := os.Stat(path); err != nil || info.Mode().Perm() != 0o600 {
		t.Errorf("langfuse.env mode = %v (%v), want 0600", info.Mode().Perm(), err)
	}
}

// Without an answer the core keeps the development pair the sample carries.
func TestLangfuseBlankKeepsTheDevelopmentPair(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{}
	e := &Env{Samples: &Samples{Core: ParseSample("LANGFUSE_PUBLIC_KEY=pk-lf-kumoss-dev\n")}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := ReadEnv(p.Core)["LANGFUSE_PUBLIC_KEY"]; got != "pk-lf-kumoss-dev" {
		t.Errorf("LANGFUSE_PUBLIC_KEY = %q, want the sample's development pair", got)
	}
}

// Enabling the mapping sidecar must mint its bearer token: the core refuses to
// boot when the service is on and the token resolves empty. It was written
// blank because generation still said "disabled by default".
func TestMappingEnabledGeneratesTheSharedToken(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{Mapping: state.Mapping{Enabled: true}}
	e := &Env{Samples: &Samples{
		Core:    ParseSample("KUMOSS_MAPPING_TOKEN=\n"),
		Mapping: ParseSample("KUMOSS_MAPPING_TOKEN=\n"),
	}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}

	token := ReadEnv(p.Mapping)["KUMOSS_MAPPING_TOKEN"]
	if token == "" {
		t.Fatal("KUMOSS_MAPPING_TOKEN is blank in services/mapping/.env with mapping enabled")
	}
	if got := ReadEnv(p.Core)["KUMOSS_MAPPING_TOKEN"]; got != token {
		t.Errorf("core/.env token = %q, sidecar = %q, want the same value", got, token)
	}
}

// A reconfigure keeps the token already on disk, so the running sidecar keeps
// accepting the core it was started with.
func TestMappingTokenIsKeptAcrossRewrites(t *testing.T) {
	p := envPathsIn(t)
	e := &Env{Samples: &Samples{
		Core:    ParseSample("KUMOSS_MAPPING_TOKEN=\n"),
		Mapping: ParseSample("KUMOSS_MAPPING_TOKEN=\n"),
	}}
	if err := e.Write(p, &state.State{Mapping: state.Mapping{Enabled: true}}); err != nil {
		t.Fatalf("Write: %v", err)
	}
	token := ReadEnv(p.Mapping)["KUMOSS_MAPPING_TOKEN"]

	s := &state.State{Mapping: state.Mapping{Enabled: true}}
	existing, _ := LoadSecrets(p)
	Fill(s, existing, nil)
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := ReadEnv(p.Mapping)["KUMOSS_MAPPING_TOKEN"]; got != token {
		t.Errorf("token rotated from %q to %q on a reconfigure", token, got)
	}
}

// A fresh install has no mapping env file to copy from, so the built-in list
// has to carry LOG_LEVEL or the service starts without one.
func TestMappingFallbackKeepsTheDefaultLogLevel(t *testing.T) {
	p := envPathsIn(t)
	if err := (&Env{}).Write(p, &state.State{Mapping: state.Mapping{Enabled: true}}); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := ReadEnv(p.Mapping)["LOG_LEVEL"]; got != "INFO" {
		t.Errorf("LOG_LEVEL = %q, want INFO", got)
	}
}
