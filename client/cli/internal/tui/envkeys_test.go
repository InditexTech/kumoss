// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"slices"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// kumoss run blocks on a blank required credential, so a variable whose own
// help text calls a blank supported must not appear here: Vertex falls back to
// Application Default Credentials, and demanding the key would block a
// working stack.
func TestRequiredEnvKeysDropsTheOptionalCredentials(t *testing.T) {
	s := &state.State{LLM: state.LLM{Providers: []string{"vertex_ai"}, Model: "vertex_ai/claude-sonnet-5-5"}}

	got := RequiredEnvKeys(s)

	for _, want := range []string{"VERTEXAI_PROJECT", "VERTEXAI_LOCATION"} {
		if !slices.Contains(got, want) {
			t.Errorf("%s is required but missing from %v", want, got)
		}
	}
	if slices.Contains(got, "VERTEXAI_CREDENTIALS") {
		t.Errorf("VERTEXAI_CREDENTIALS is optional but was listed: %v", got)
	}
}

// Every key stays in EnvKeys: status reports what is set, required or not.
func TestEnvKeysStillListsTheOptionalCredentials(t *testing.T) {
	if got := EnvKeys("vertex_ai"); !slices.Contains(got, "VERTEXAI_CREDENTIALS") {
		t.Errorf("EnvKeys dropped an optional credential: %v", got)
	}
}

// A provider with one mandatory key keeps it.
func TestRequiredEnvKeysKeepsASoleAPIKey(t *testing.T) {
	s := &state.State{LLM: state.LLM{Providers: []string{"anthropic"}, Model: "anthropic/claude-sonnet-5"}}

	if got := RequiredEnvKeys(s); !slices.Equal(got, []string{"ANTHROPIC_API_KEY"}) {
		t.Errorf("RequiredEnvKeys = %v, want [ANTHROPIC_API_KEY]", got)
	}
}

// Two providers mean two credential sets the core reads at boot, so both are
// reported: missing one would let a stack start that cannot call a model.
func TestRequiredEnvKeysCoversBothProviders(t *testing.T) {
	s := &state.State{LLM: state.LLM{
		Providers:  []string{"anthropic", "vertex_ai"},
		Model:      "anthropic/claude-sonnet-5-5",
		SmallModel: "vertex_ai/gemini-3.8-flash",
	}}

	got := RequiredEnvKeys(s)

	for _, want := range []string{"ANTHROPIC_API_KEY", "VERTEXAI_PROJECT", "VERTEXAI_LOCATION"} {
		if !slices.Contains(got, want) {
			t.Errorf("%s is required but missing from %v", want, got)
		}
	}
}
