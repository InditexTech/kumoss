// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import "testing"

// The form shows the values config.yaml already holds, so a fresh install does
// not present blank knobs for settings that have a default.
func TestLLMDefaultsReadTheConfigDocument(t *testing.T) {
	doc := map[string]any{"llm": map[string]any{
		"model": "vertex_ai/x", "small_model": "vertex_ai/y",
		"temperature": 0.2, "max_output_tokens": 32000, "timeout": 900,
	}}
	d := llmDefaults(doc)
	if d.model != "vertex_ai/x" || d.small != "vertex_ai/y" {
		t.Errorf("models = %s / %s", d.model, d.small)
	}
	if d.temperature != "0.2" || d.maxTokens != "32000" || d.timeout != "900" {
		t.Errorf("knobs = %q %q %q", d.temperature, d.maxTokens, d.timeout)
	}
}

// A missing or malformed llm block leaves every default blank: the wizard still
// runs and the state keeps no answer, so the file's own value survives.
func TestLLMDefaultsTolerateAMissingBlock(t *testing.T) {
	for _, doc := range []map[string]any{nil, {}, {"llm": "not a map"}} {
		if d := llmDefaults(doc); d != (llmSeed{}) {
			t.Errorf("llmDefaults(%v) = %+v, want the zero seed", doc, d)
		}
	}
}
