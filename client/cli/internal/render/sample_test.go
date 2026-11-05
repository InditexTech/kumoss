// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import "testing"

// Provider credentials are commented out in core/env.sample, so a sample-only
// pass dropped them. They must be written whenever the wizard collected them.
func TestResolveSampleKeepsUnownedCredentials(t *testing.T) {
	sample := ParseSample("KUMOSS_IAC_TOKEN=dev-token\n")
	owned := map[string]string{
		"KUMOSS_IAC_TOKEN":     "real-token",
		"VERTEXAI_PROJECT":     "my-project",
		"VERTEXAI_CREDENTIALS": `{"type":"service_account"}`,
		// Blank values must not be written: they would shadow a provider default.
		"VERTEXAI_LOCATION": "",
	}
	got := resolveSample(sample, owned, nil)

	if got["KUMOSS_IAC_TOKEN"] != "real-token" {
		t.Errorf("sample key lost its wizard value: %q", got["KUMOSS_IAC_TOKEN"])
	}
	if got["VERTEXAI_PROJECT"] != "my-project" {
		t.Errorf("VERTEXAI_PROJECT dropped: %q", got["VERTEXAI_PROJECT"])
	}
	if got["VERTEXAI_CREDENTIALS"] == "" {
		t.Error("VERTEXAI_CREDENTIALS dropped")
	}
	if _, ok := got["VERTEXAI_LOCATION"]; ok {
		t.Error("blank credential written")
	}
}
