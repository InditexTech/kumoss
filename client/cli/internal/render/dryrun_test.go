// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// RenderConfig is what `init --dry-run` prints, so it must be the same overlay
// Write applies, and must keep the keys the forms do not own.
func TestRenderConfigOverlaysTheAnswers(t *testing.T) {
	s := &state.State{
		LLM:     state.LLM{Model: "anthropic/x", SmallModel: "anthropic/y", Temperature: 0.3},
		Git:     state.Git{Provider: "GITHUB", AuthorName: "Bot", AuthorEmail: "bot@example.invalid"},
		Storage: state.Storage{Provider: "RUSTFS", Bucket: "b", TerraformStateBucket: "t"},
	}
	out, err := RenderConfig([]byte(repoDefault), s)
	if err != nil {
		t.Fatalf("RenderConfig: %v", err)
	}

	var doc map[string]any
	if err := yaml.Unmarshal(out, &doc); err != nil {
		t.Fatalf("output is not valid YAML: %v", err)
	}
	llm := doc["llm"].(map[string]any)
	if llm["model"] != "anthropic/x" || llm["temperature"] != 0.3 {
		t.Errorf("llm not overlaid: %v", llm)
	}
	if doc["git"].(map[string]any)["provider"] != "GITHUB" {
		t.Errorf("git not overlaid: %v", doc["git"])
	}
	if doc["storage"].(map[string]any)["bucket"] != "b" {
		t.Errorf("storage not overlaid: %v", doc["storage"])
	}
	// Keys the forms never touch must survive the round-trip.
	if doc["environment"] != "development" {
		t.Errorf("unowned key lost: %v", doc["environment"])
	}
}

// A file that is not ours must fail loudly rather than be silently replaced.
func TestRenderConfigRejectsInvalidYAML(t *testing.T) {
	if _, err := RenderConfig([]byte("\tnot: [valid"), &state.State{}); err == nil {
		t.Error("RenderConfig accepted invalid YAML")
	}
}

// An empty file is treated as an empty document, not a crash.
func TestRenderConfigAcceptsEmpty(t *testing.T) {
	out, err := RenderConfig(nil, &state.State{LLM: state.LLM{Model: "m"}})
	if err != nil {
		t.Fatalf("RenderConfig: %v", err)
	}
	if len(out) == 0 {
		t.Error("empty output")
	}
}

// Files is the dry-run view of Write: it must produce the same paths and the
// same generated tokens, and must not write anything.
func TestEnvFilesDoesNotTouchTheDisk(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{}
	e := &Env{Samples: &Samples{Core: ParseSample("KUMOSS_IAC_TOKEN=\n"), IAC: ParseSample(""), Notifications: ParseSample("")}}

	files := e.Files(p, s)
	if len(files) != 3 {
		t.Fatalf("files = %d, want 3", len(files))
	}
	if s.Secrets.IACToken == "" {
		t.Error("Files did not generate the token it shows")
	}
	if got := files[p.Core]["KUMOSS_IAC_TOKEN"]; got != s.Secrets.IACToken {
		t.Errorf("shown token %q != generated %q", got, s.Secrets.IACToken)
	}
	if len(readEnv(p.Core)) != 0 {
		t.Error("Files wrote to the disk")
	}
}

// Write generates each token exactly once: calling generate twice would write
// one token to the file and leave a different one on the state.
func TestWriteGeneratesEachTokenOnce(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{}
	e := &Env{Samples: &Samples{
		Core:          ParseSample("KUMOSS_IAC_TOKEN=\nKUMOSS_NOTIFICATIONS_TOKEN=\n"),
		IAC:           ParseSample("KUMOSS_IAC_TOKEN=\n"),
		Notifications: ParseSample("KUMOSS_NOTIFICATIONS_TOKEN=\n"),
	}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}

	core := readEnv(p.Core)
	if core["KUMOSS_IAC_TOKEN"] != s.Secrets.IACToken {
		t.Errorf("core iac token %q != state %q", core["KUMOSS_IAC_TOKEN"], s.Secrets.IACToken)
	}
	if core["KUMOSS_NOTIFICATIONS_TOKEN"] != s.Secrets.NotificationsToken {
		t.Errorf("core notif token %q != state %q", core["KUMOSS_NOTIFICATIONS_TOKEN"], s.Secrets.NotificationsToken)
	}
}
