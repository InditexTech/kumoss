// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// A field the user may leave blank says so; one the stack needs says that, so
// the form never leaves it to guesswork.
func TestTitledMarksRequiredAndOptional(t *testing.T) {
	if got := titled("API key", false); got != "API key (required)" {
		t.Errorf("required title = %q", got)
	}
	if got := titled("API base", true); got != "API base (optional)" {
		t.Errorf("optional title = %q", got)
	}
}

// The two storage endpoints are different addresses of one store, and the form
// has to say which is which: the first is the core's, the second the browser's.
func TestStorageEndpointDescriptionsExplainTheTwoAddresses(t *testing.T) {
	d := storageDescriptions()
	if !strings.Contains(d[0], "In-cluster") || !strings.Contains(d[0], "writes") {
		t.Errorf("endpoint description = %q", d[0])
	}
	if !strings.Contains(d[1], "Browser-facing") || !strings.Contains(d[1], "signed") {
		t.Errorf("public endpoint description = %q", d[1])
	}
}

// The webhook is asked for only once notifications are on: with "No" the form
// is one question, and a blank URL never reaches the file.
func TestWebhookHidesUntilNotificationsAreEnabled(t *testing.T) {
	if !notificationsWebhookHidden(&state.State{}) {
		t.Error("webhook visible while notifications are off")
	}
	if notificationsWebhookHidden(&state.State{Notifications: state.Notifications{Enabled: true}}) {
		t.Error("webhook hidden while notifications are on")
	}
}

// The credential fields the provider table calls optional are the ones the form
// marks optional: a divergence would ask for a value a working setup omits.
func TestOptionalCredentialsAreTheOnesMarkedOptional(t *testing.T) {
	for _, p := range llmProviders {
		for _, c := range p.Credentials {
			optional := strings.HasSuffix(titled(c.Title, optionalCredentials[c.Name]), optionalTitle)
			if optional != optionalCredentials[c.Name] {
				t.Errorf("%s (%s) marked optional=%v", c.Name, p.Name, optional)
			}
		}
	}
}

// The provider pick is a multi-select capped at two: one vendor for both roles,
// or two to split them. Zero is refused before any credential form opens.
func TestProviderOptionsCapAtTwo(t *testing.T) {
	if providerLimit != 2 {
		t.Errorf("providerLimit = %d, want 2", providerLimit)
	}
}

// A required credential cannot be submitted blank; the optional ones can.
func TestRequiredCredentialsRejectBlank(t *testing.T) {
	if err := required("  "); err == nil {
		t.Error("blank passed the required validator")
	}
	if !optionalCredentials["VERTEXAI_CREDENTIALS"] {
		t.Error("VERTEXAI_CREDENTIALS must stay optional: blank means ADC")
	}
}
