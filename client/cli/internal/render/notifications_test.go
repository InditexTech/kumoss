// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// configDoc parses rendered config.yaml bytes.
func configDoc(t *testing.T, raw []byte) map[string]any {
	t.Helper()
	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("rendered config is not valid YAML: %v", err)
	}
	return doc
}

// The notifications answer must reach services.notifications.enabled, and the
// endpoint/token_env/timeout the wizard does not own must survive: dropping them
// would leave the core pointing at no service.
func TestConfigWritesNotificationsEnabled(t *testing.T) {
	for _, enabled := range []bool{true, false} {
		out, err := RenderConfig([]byte(repoDefault), &state.State{Notifications: state.Notifications{Enabled: enabled}})
		if err != nil {
			t.Fatalf("RenderConfig: %v", err)
		}

		services := configDoc(t, out)["services"].(map[string]any)
		notifications := services["notifications"].(map[string]any)
		if got := notifications["enabled"]; got != enabled {
			t.Errorf("enabled = %v, want %v", got, enabled)
		}
		if notifications["endpoint"] != "http://notifications:8080" {
			t.Errorf("endpoint lost: %v", notifications["endpoint"])
		}
		if notifications["token_env"] != "KUMOSS_NOTIFICATIONS_TOKEN" {
			t.Errorf("token_env lost: %v", notifications["token_env"])
		}
		// The other sidecars are untouched.
		if _, ok := services["iac"].(map[string]any); !ok {
			t.Errorf("iac block lost: %v", services)
		}
		if services["mapping"].(map[string]any)["enabled"] != false {
			t.Errorf("mapping block changed: %v", services["mapping"])
		}
	}
}

// A config.yaml without a services: block still gets one, rather than a panic or
// a dropped answer.
func TestConfigCreatesNotificationsBlockWhenAbsent(t *testing.T) {
	raw := "llm:\n  model: x\n"
	out, err := RenderConfig([]byte(raw), &state.State{Notifications: state.Notifications{Enabled: true}})
	if err != nil {
		t.Fatalf("RenderConfig: %v", err)
	}
	services := configDoc(t, out)["services"].(map[string]any)
	if services["notifications"].(map[string]any)["enabled"] != true {
		t.Errorf("enabled not written: %v", services)
	}
}

// The webhook goes into the notifications .env under SLACK_WEBHOOK_URL, and the
// token stays beside it: the service needs both to start and to authenticate.
func TestEnvWritesSlackWebhook(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{
		Notifications: state.Notifications{SlackWebhookURL: "https://hooks.slack.com/services/x"},
		Secrets:       state.Secrets{NotificationsToken: "tok"},
	}
	e := &Env{Samples: &Samples{Core: ParseSample(""), IAC: ParseSample(""), Notifications: ParseSample("SLACK_WEBHOOK_URL=\nKUMOSS_NOTIFICATIONS_TOKEN=\n")}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}

	got := readEnv(p.Notifications)
	if got["SLACK_WEBHOOK_URL"] != "https://hooks.slack.com/services/x" {
		t.Errorf("SLACK_WEBHOOK_URL = %q", got["SLACK_WEBHOOK_URL"])
	}
	if got["KUMOSS_NOTIFICATIONS_TOKEN"] != "tok" {
		t.Errorf("token = %q", got["KUMOSS_NOTIFICATIONS_TOKEN"])
	}
}

// Without samples the built-in key list must still carry the webhook, or a
// failed fetch would write a notifications file the service cannot boot from.
func TestFallbackEnvWritesSlackWebhook(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{Notifications: state.Notifications{SlackWebhookURL: "https://hooks.slack.com/services/y"}}
	if err := (&Env{}).Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := readEnv(p.Notifications)["SLACK_WEBHOOK_URL"]; got != "https://hooks.slack.com/services/y" {
		t.Errorf("SLACK_WEBHOOK_URL = %q", got)
	}
}

// The webhook is a secret: it must never reach kumoss.yaml.
func TestSlackWebhookIsNotPersisted(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kumoss.yaml")
	s := &state.State{Notifications: state.Notifications{Enabled: true, SlackWebhookURL: "https://hooks.slack.com/services/z"}}
	if err := state.Save(path, s); err != nil {
		t.Fatalf("Save: %v", err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if strings.Contains(string(raw), "hooks.slack.com") {
		t.Errorf("kumoss.yaml carries the webhook:\n%s", raw)
	}

	got, err := state.Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !got.Notifications.Enabled {
		t.Error("enabled did not round-trip")
	}
	if got.Notifications.SlackWebhookURL != "" {
		t.Errorf("webhook survived the round-trip: %q", got.Notifications.SlackWebhookURL)
	}
}
