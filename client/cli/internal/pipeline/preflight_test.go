// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// configuredConfigYAML is what the renderer would have written for the state
// configured() returns, so a consistent install reports nothing.
const configuredConfigYAML = `llm:
  model: anthropic/claude-sonnet-5
  small_model: anthropic/claude-haiku-4-5
git:
  provider: GITHUB
  author_name: Kumoss
  author_email: kumoss@noreply.invalid
storage:
  provider: RUSTFS
  bucket: kumoss-artifacts
  terraform_state_bucket: kumoss-terraform-state
services:
  notifications:
    enabled: false
  iac:
    endpoint: http://iac:8082
`

// configured writes a home whose files agree with the state it returns: the
// baseline every test below breaks in exactly one way.
func configured(t *testing.T) (home.Home, *state.State) {
	t.Helper()
	h := home.Home{Root: t.TempDir()}
	if err := h.Ensure(); err != nil {
		t.Fatalf("Ensure: %v", err)
	}
	write(t, h.ComposeFile(), "services: {}\n")
	write(t, h.ComposeOverride(), "services: {}\n")
	write(t, h.ConfigYAML(), configuredConfigYAML)
	write(t, h.CoreEnv(), "ANTHROPIC_API_KEY=sk-test\nKUMOSS_IAC_TOKEN=shared-iac\n")
	write(t, h.ServiceEnv("iac"), "KUMOSS_IAC_TOKEN=shared-iac\n")

	s := &state.State{
		SchemaVersion: 1,
		LLM: state.LLM{
			Provider:   "anthropic",
			Model:      "anthropic/claude-sonnet-5",
			SmallModel: "anthropic/claude-haiku-4-5",
		},
		Git:           state.Git{Provider: "GITHUB", AuthorName: "Kumoss", AuthorEmail: "kumoss@noreply.invalid"},
		Storage:       state.Storage{Provider: "RUSTFS", Bucket: "kumoss-artifacts", TerraformStateBucket: "kumoss-terraform-state"},
		Notifications: state.Notifications{Enabled: false},
	}
	return h, s
}

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatalf("mkdir %s: %v", path, err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

// messages joins the report, so an assertion can look for a substring without
// caring which problem carried it.
func messages(problems []Problem) string {
	var b strings.Builder
	for _, p := range problems {
		b.WriteString(p.Message)
		b.WriteString(" [")
		b.WriteString(p.Fix)
		b.WriteString("]\n")
	}
	return b.String()
}

// The baseline must be silent, or every other test here proves nothing.
func TestPreflightPassesOnAConsistentInstall(t *testing.T) {
	h, s := configured(t)

	if got := Preflight(h, s); len(got) != 0 {
		t.Errorf("a consistent install reported problems:\n%s", messages(got))
	}
}

// A hand-edited config.yaml is the case kumoss.yaml exists to catch: the
// containers would boot on a value the recorded answers never chose.
func TestPreflightReportsConfigYAMLDrift(t *testing.T) {
	for _, c := range []struct {
		name    string
		edit    string
		to      string
		wantKey string
		wantFix string
	}{
		{"llm model", "model: anthropic/claude-sonnet-5", "model: openai/gpt-5", "llm.model", "kumoss config llm"},
		{"git author", "author_email: kumoss@noreply.invalid", "author_email: someone@else.invalid", "git.author_email", "kumoss config git"},
		{"storage bucket", "bucket: kumoss-artifacts", "bucket: other-bucket", "storage.bucket", "kumoss config state"},
		{"notifications", "enabled: false", "enabled: true", "services.notifications.enabled", "kumoss config notifications"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h, s := configured(t)
			edited := strings.Replace(configuredConfigYAML, c.edit, c.to, 1)
			if edited == configuredConfigYAML {
				t.Fatalf("the fixture no longer contains %q", c.edit)
			}
			write(t, h.ConfigYAML(), edited)

			got := Preflight(h, s)

			if len(got) != 1 {
				t.Fatalf("want 1 problem, got %d:\n%s", len(got), messages(got))
			}
			if !strings.Contains(got[0].Message, c.wantKey) {
				t.Errorf("the problem does not name %s: %q", c.wantKey, got[0].Message)
			}
			if got[0].Fix != c.wantFix {
				t.Errorf("Fix = %q, want %q", got[0].Fix, c.wantFix)
			}
		})
	}
}

// The wizard owns a handful of keys; everything else in config.yaml is the
// user's to edit, and reporting it would make run unusable on a tuned stack.
func TestPreflightIgnoresConfigKeysTheWizardDoesNotOwn(t *testing.T) {
	h, s := configured(t)
	write(t, h.ConfigYAML(), configuredConfigYAML+"oidc:\n  issuer_url: https://idp.example.invalid\norchestration:\n  max_drift_reports: 9\n")

	if got := Preflight(h, s); len(got) != 0 {
		t.Errorf("an unowned key was reported as drift:\n%s", messages(got))
	}
}

// The cloud answers are recorded now, so a hand-edited iac/.env is caught the
// same way config.yaml is.
func TestPreflightReportsCloudEnvDrift(t *testing.T) {
	h, s := configured(t)
	s.Cloud.AWS = &state.AWSAuth{Method: "static", Region: "eu-west-1"}
	write(t, h.ServiceEnv("iac"),
		"KUMOSS_IAC_TOKEN=shared-iac\nAWS_REGION=us-east-1\nAWS_ACCESS_KEY_ID=AKIA\nAWS_SECRET_ACCESS_KEY=sk\n")

	got := Preflight(h, s)

	if len(got) != 1 {
		t.Fatalf("want 1 problem, got %d:\n%s", len(got), messages(got))
	}
	if !strings.Contains(got[0].Message, "AWS_REGION") {
		t.Errorf("the problem does not name AWS_REGION: %q", got[0].Message)
	}
	if got[0].Fix != "kumoss config cloud" {
		t.Errorf("Fix = %q, want kumoss config cloud", got[0].Fix)
	}
}

// A credential kumoss.yaml deliberately never stores can only be checked for
// presence — there is no recorded value to compare against.
func TestPreflightReportsABlankCloudCredential(t *testing.T) {
	h, s := configured(t)
	s.Cloud.AWS = &state.AWSAuth{Method: "static", Region: "eu-west-1"}
	write(t, h.ServiceEnv("iac"),
		"KUMOSS_IAC_TOKEN=shared-iac\nAWS_REGION=eu-west-1\nAWS_ACCESS_KEY_ID=\nAWS_SECRET_ACCESS_KEY=\n")

	msg := messages(Preflight(h, s))

	for _, key := range []string{"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"} {
		if !strings.Contains(msg, key) {
			t.Errorf("%s was not reported as blank:\n%s", key, msg)
		}
	}
}

// A named profile authenticates from the mounted ~/.aws, so demanding static
// keys there would block a valid setup.
func TestPreflightDoesNotDemandStaticKeysForAnAWSProfile(t *testing.T) {
	h, s := configured(t)
	s.Cloud.AWS = &state.AWSAuth{Method: "profile", Profile: "corp", Region: "eu-west-1"}
	write(t, h.ServiceEnv("iac"), "KUMOSS_IAC_TOKEN=shared-iac\nAWS_REGION=eu-west-1\n"+
		"AWS_PROFILE=corp\nAWS_SHARED_CREDENTIALS_FILE="+render.ContainerAWSProfile+"/credentials\n")

	if got := Preflight(h, s); len(got) != 0 {
		t.Errorf("a profile-based AWS setup reported problems:\n%s", messages(got))
	}
}

// The credential set follows the provider in llm.model: an anthropic stack
// with no key never reaches a first inference.
func TestPreflightReportsABlankLLMCredential(t *testing.T) {
	h, s := configured(t)
	write(t, h.CoreEnv(), "ANTHROPIC_API_KEY=\nKUMOSS_IAC_TOKEN=shared-iac\n")

	got := Preflight(h, s)

	if len(got) != 1 {
		t.Fatalf("want 1 problem, got %d:\n%s", len(got), messages(got))
	}
	if !strings.Contains(got[0].Message, "ANTHROPIC_API_KEY") {
		t.Errorf("the problem does not name ANTHROPIC_API_KEY: %q", got[0].Message)
	}
	if got[0].Fix != "kumoss config llm" {
		t.Errorf("Fix = %q, want kumoss config llm", got[0].Fix)
	}
}

// Some provider variables document a blank as a supported setup — Vertex falls
// back to Application Default Credentials — so demanding them blocks a
// working stack.
func TestPreflightAllowsABlankOptionalLLMCredential(t *testing.T) {
	h, s := configured(t)
	s.LLM = state.LLM{
		Provider:   "vertex_ai",
		Model:      "vertex_ai/claude-sonnet-5-5",
		SmallModel: "vertex_ai/gemini-3.8-flash",
	}
	write(t, h.ConfigYAML(), strings.NewReplacer(
		"anthropic/claude-sonnet-5", "vertex_ai/claude-sonnet-5-5",
		"anthropic/claude-haiku-4-5", "vertex_ai/gemini-3.8-flash",
	).Replace(configuredConfigYAML))
	write(t, h.CoreEnv(),
		"VERTEXAI_PROJECT=a-project\nVERTEXAI_LOCATION=europe-west1\nVERTEXAI_CREDENTIALS=\nKUMOSS_IAC_TOKEN=shared-iac\n")

	if got := Preflight(h, s); len(got) != 0 {
		t.Errorf("a blank optional credential was reported:\n%s", messages(got))
	}
}

// The core sends this token and the sidecar validates it, so a mismatch is a
// 401 on every call rather than a boot failure — and the values must never
// reach the screen.
func TestPreflightReportsAServiceTokenMismatchWithoutPrintingIt(t *testing.T) {
	h, s := configured(t)
	write(t, h.ServiceEnv("iac"), "KUMOSS_IAC_TOKEN=a-different-token\n")

	got := Preflight(h, s)

	if len(got) != 1 {
		t.Fatalf("want 1 problem, got %d:\n%s", len(got), messages(got))
	}
	if !strings.Contains(got[0].Message, "KUMOSS_IAC_TOKEN") {
		t.Errorf("the problem does not name the token: %q", got[0].Message)
	}
	if got[0].Fix != "kumoss config secrets" {
		t.Errorf("Fix = %q, want kumoss config secrets", got[0].Fix)
	}
	for _, secret := range []string{"a-different-token", "shared-iac"} {
		if strings.Contains(messages(got), secret) {
			t.Errorf("the report printed the token value %q", secret)
		}
	}
}

// The core refuses to boot on an empty iac token, and iac cannot be disabled.
func TestPreflightReportsABlankServiceToken(t *testing.T) {
	h, s := configured(t)
	write(t, h.CoreEnv(), "ANTHROPIC_API_KEY=sk-test\nKUMOSS_IAC_TOKEN=\n")
	write(t, h.ServiceEnv("iac"), "KUMOSS_IAC_TOKEN=\n")

	msg := messages(Preflight(h, s))

	if !strings.Contains(msg, "KUMOSS_IAC_TOKEN") {
		t.Errorf("a blank iac token was not reported:\n%s", msg)
	}
}

// The notifications service refuses to start without a webhook, so an enabled
// stack with a blank one dies on the first boot.
func TestPreflightReportsABlankSlackWebhookWhenNotificationsAreOn(t *testing.T) {
	h, s := configured(t)
	s.Notifications.Enabled = true
	write(t, h.ConfigYAML(), strings.Replace(configuredConfigYAML, "enabled: false", "enabled: true", 1))
	write(t, h.CoreEnv(), "ANTHROPIC_API_KEY=sk-test\nKUMOSS_IAC_TOKEN=shared-iac\nKUMOSS_NOTIFICATIONS_TOKEN=notif\n")
	write(t, h.ServiceEnv("notifications"), "KUMOSS_NOTIFICATIONS_TOKEN=notif\nSLACK_WEBHOOK_URL=\n")

	got := Preflight(h, s)

	if len(got) != 1 {
		t.Fatalf("want 1 problem, got %d:\n%s", len(got), messages(got))
	}
	if !strings.Contains(got[0].Message, "SLACK_WEBHOOK_URL") {
		t.Errorf("the problem does not name the webhook: %q", got[0].Message)
	}
	if got[0].Fix != "kumoss config notifications" {
		t.Errorf("Fix = %q, want kumoss config notifications", got[0].Fix)
	}
}

// A variable the user added by hand is theirs: the wizard writes the sample's
// keys plus its own, and reporting the rest would make run unusable.
func TestPreflightIgnoresEnvKeysTheWizardDoesNotOwn(t *testing.T) {
	h, s := configured(t)
	write(t, h.CoreEnv(), "ANTHROPIC_API_KEY=sk-test\nKUMOSS_IAC_TOKEN=shared-iac\nMY_OWN_PROXY=http://proxy.invalid\n")

	if got := Preflight(h, s); len(got) != 0 {
		t.Errorf("an unowned env key was reported:\n%s", messages(got))
	}
}

// A file the stack mounts cannot be regenerated by a section edit, so the fix
// is init rather than config.
func TestPreflightReportsAMissingGeneratedFile(t *testing.T) {
	h, s := configured(t)
	if err := os.Remove(h.ConfigYAML()); err != nil {
		t.Fatalf("remove: %v", err)
	}

	got := Preflight(h, s)

	if len(got) != 1 {
		t.Fatalf("want 1 problem, got %d:\n%s", len(got), messages(got))
	}
	if !strings.Contains(got[0].Message, h.ConfigYAML()) {
		t.Errorf("the problem does not name the file: %q", got[0].Message)
	}
	if got[0].Fix != "kumoss init" {
		t.Errorf("Fix = %q, want kumoss init", got[0].Fix)
	}
}

// The notifications env file only exists when the service is on, so demanding
// it from a stack that disabled notifications would block a valid install.
func TestPreflightIgnoresTheNotificationsEnvWhenDisabled(t *testing.T) {
	h, s := configured(t)

	if got := Preflight(h, s); len(got) != 0 {
		t.Fatalf("disabled notifications reported problems:\n%s", messages(got))
	}

	s.Notifications.Enabled = true
	write(t, h.ConfigYAML(), strings.Replace(configuredConfigYAML, "enabled: false", "enabled: true", 1))

	got := Preflight(h, s)
	if !strings.Contains(messages(got), h.ServiceEnv("notifications")) {
		t.Errorf("enabling notifications did not demand its env file:\n%s", messages(got))
	}
}
