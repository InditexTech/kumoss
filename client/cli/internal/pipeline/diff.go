// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"regexp"
	"strings"
)

// secretLine matches the lines whose value is never shown: env tokens and
// credentials, plus the YAML keys that carry a credential map.
var secretLine = regexp.MustCompile(`(?i)(TOKEN|SECRET|PASSWORD|_KEY|CREDENTIALS|WEBHOOK|access_key|secret_key)`)

// maskValue is what replaces a secret in the diff.
const maskValue = "<redacted>"

// maskLines splits rendered text into lines with every secret masked. It works
// on the rendered form, so one masking covers .env and YAML alike.
func maskLines(s string) []string {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	for i, line := range lines {
		lines[i] = maskLine(line)
	}
	return lines
}

// maskLine keeps the key and replaces the value.
func maskLine(line string) string {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" || strings.HasPrefix(trimmed, "#") {
		return line
	}
	if !secretLine.MatchString(trimmed) {
		return line
	}
	sep := "="
	if i := strings.IndexAny(trimmed, "=:"); i >= 0 {
		sep = trimmed[i : i+1]
		trimmed = trimmed[:i]
	}
	return strings.TrimSpace(trimmed) + sep + maskValue
}

// keyOf is the line's key, so a diff pairs before and after by key rather than
// by position.
func keyOf(line string) string {
	trimmed := strings.TrimSpace(line)
	if i := strings.IndexAny(trimmed, "=:"); i >= 0 {
		return strings.TrimSpace(trimmed[:i])
	}
	return trimmed
}
