// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strconv"
)

// llmSeed is what config.yaml offers the LLM form when the state holds no
// answer. Strings, because that is what the form binds and parses back.
type llmSeed struct {
	model, small string
	temperature  string
	maxTokens    string
	timeout      string
}

// llmDefaults reads the llm block of the config.yaml the CLI downloaded. Any
// missing key or wrong type leaves that field blank, so a hand-edited file
// that does not parse still leaves a usable wizard.
func llmDefaults(doc map[string]any) llmSeed {
	llm, _ := doc["llm"].(map[string]any)
	return llmSeed{
		model:       stringOf(llm["model"]),
		small:       stringOf(llm["small_model"]),
		temperature: numberOf(llm["temperature"]),
		maxTokens:   numberOf(llm["max_output_tokens"]),
		timeout:     numberOf(llm["timeout"]),
	}
}

func stringOf(v any) string {
	s, _ := v.(string)
	return s
}

// firstNonEmpty is the state's answer, or the file's seed when it has none.
func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// numberOf formats a YAML number the way the form shows it; yaml.v3 decodes an
// integer as int and a decimal as float64.
func numberOf(v any) string {
	switch n := v.(type) {
	case int:
		return strconv.Itoa(n)
	case float64:
		return strconv.FormatFloat(n, 'g', -1, 64)
	}
	return ""
}
