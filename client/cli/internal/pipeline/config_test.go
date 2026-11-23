// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// A rewritten mount block changes the service definition, so the container has
// to be replaced, not just restarted. Anything that leaves the definition
// alone keeps the narrower recreate list.
func TestSameDefinitionFollowsTheMounts(t *testing.T) {
	h := home.Home{Root: "/home/u/.kumoss"}
	base := &state.State{Engine: state.Engine{Binary: "tofu"}}

	if !sameDefinition(h, base, base.Copy()) {
		t.Error("an unchanged state reported a different definition")
	}

	withKey := base.Copy()
	withKey.Cloud.GCP = &state.GCPAuth{Method: "file", KeyFile: "/keys/sa.json"}
	if sameDefinition(h, base, withKey) {
		t.Error("a new credential mount left the definition unchanged")
	}

	otherEngine := base.Copy()
	otherEngine.Engine.Binary = "terraform"
	if sameDefinition(h, base, otherEngine) {
		t.Error("a new IaC engine left the definition unchanged")
	}
}

// stubSection is a SectionUI whose section leaves the state untouched, so a
// test can assert on what RunConfig carried over before the form opened.
type stubSection struct{}

func (stubSection) LLM(*state.State) error           { return nil }
func (stubSection) Git(*state.State) error           { return nil }
func (stubSection) Cloud(*state.State) error         { return nil }
func (stubSection) Engine(*state.State) error        { return nil }
func (stubSection) State(*state.State) error         { return nil }
func (stubSection) Notifications(*state.State) error { return nil }
func (stubSection) RotateSecrets([]Secret) ([]string, error) {
	return nil, nil
}

// Every value the yaml drops must be read back from the env files before the
// section runs, or the write that follows erases it. Editing one section used
// to clear the LLM key, the Git token, the cloud credentials and the webhook.
// to clear the LLM key, the Git token, the cloud credentials and the webhook.
func TestConfigKeepsTheValuesTheYamlCannotHold(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	for _, dir := range []string{h.ConfigDir(), h.CoreDir(), h.ServicesDir("iac"), h.ServicesDir("notifications")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	saved := &state.State{
		LLM:           state.LLM{Model: "anthropic/claude", Credentials: map[string]string{"ANTHROPIC_API_KEY": "llm-key"}},
		Git:           state.Git{Provider: "GITHUB", User: "me", Token: "git-token"},
		Cloud:         state.Cloud{AWS: &state.AWSAuth{Method: "static", AccessKey: "AKIA", SecretKey: "aws-secret"}},
		Notifications: state.Notifications{Enabled: true, SlackWebhookURL: "https://hooks.slack.test/x"},
		Storage:       state.Storage{Provider: "rustfs", Credentials: map[string]string{"STORAGE_ACCOUNT_KEY": "storage-key"}},
		Secrets:       state.Secrets{IACToken: "iac-token", NotificationsToken: "notif-token"},
	}
	if err := state.Save(h.StateFile(), saved); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ConfigExample(), []byte("llm:\n  model: repo\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ConfigYAML(), []byte("llm:\n  model: repo\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	// A minimal compose file: the recreate runs `docker compose up` for real.
	if err := os.WriteFile(h.ComposeFile(), []byte("services:\n  core:\n    image: busybox\n  iac:\n    image: busybox\n  notifications:\n    image: busybox\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ComposeOverride(), []byte("services:\n  core:\n    image: busybox\n  iac:\n    image: busybox\n  notifications:\n    image: busybox\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	env := &render.Env{}
	if err := env.Write(envPaths(h), saved.Copy()); err != nil {
		t.Fatal(err)
	}

	var shown string
	if err := RunConfig(context.Background(), ConfigOptions{
		Home:    h,
		Section: "git",
		UI:      stubSection{},
		Docker:  &stubDocker{},
		Confirm: func(diff string) (bool, error) {
			shown = diff
			return true, nil
		},
		Warn: io.Discard,
		Out:  io.Discard,
	}); err != nil {
		t.Fatalf("RunConfig: %v", err)
	}

	// The preview must not invent changes: the before side is the state the
	// files actually hold, so an untouched section shows every file unchanged.
	for _, want := range []string{"kumoss.yaml: unchanged", "config/config.yaml: unchanged"} {
		if !strings.Contains(shown, want) {
			t.Errorf("preview does not report %q:\n%s", want, shown)
		}
	}
	for _, leaked := range []string{"llm-key", "git-token", "aws-secret", "storage-key"} {
		if strings.Contains(shown, leaked) {
			t.Errorf("preview leaks %q:\n%s", leaked, shown)
		}
	}

	core := render.ReadEnv(h.CoreEnv())
	for _, c := range []struct{ key, want string }{
		{"ANTHROPIC_API_KEY", "llm-key"},
		{"GIT_USER", "me"},
		{"GIT_TOKEN", "git-token"},
		{"STORAGE_ACCOUNT_KEY", "storage-key"},
	} {
		if core[c.key] != c.want {
			t.Errorf("%s = %q, want %q", c.key, core[c.key], c.want)
		}
	}
	iac := render.ReadEnv(h.ServiceEnv("iac"))
	if iac["AWS_ACCESS_KEY_ID"] != "AKIA" || iac["AWS_SECRET_ACCESS_KEY"] != "aws-secret" {
		t.Errorf("cloud credentials lost: %q / %q", iac["AWS_ACCESS_KEY_ID"], iac["AWS_SECRET_ACCESS_KEY"])
	}
	if got := render.ReadEnv(h.ServiceEnv("notifications"))["SLACK_WEBHOOK_URL"]; got != "https://hooks.slack.test/x" {
		t.Errorf("webhook = %q, want the saved one", got)
	}
	after, err := state.Load(h.StateFile())
	if err != nil {
		t.Fatal(err)
	}
	if !after.Notifications.Enabled {
		t.Error("notifications were disabled by editing another section")
	}
}

// A section edit must not revert the hand-edited keys the forms never ask
// about. Rendering from the shipped defaults reset oidc.issuer_url to its blank
// value, which turns authentication off.
func TestConfigKeepsTheHandEditedConfig(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	for _, dir := range []string{h.ConfigDir(), h.CoreDir(), h.ServicesDir("iac"), h.ServicesDir("notifications")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	saved := &state.State{
		LLM:     state.LLM{Model: "anthropic/claude", SmallModel: "anthropic/haiku"},
		Git:     state.Git{Provider: "GITHUB", AuthorName: "Me", AuthorEmail: "me@example.com"},
		Storage: state.Storage{Provider: "rustfs", Bucket: "kumoss"},
	}
	if err := state.Save(h.StateFile(), saved); err != nil {
		t.Fatal(err)
	}
	// The shipped file, as init leaves it in config.yaml.example.
	shipped := "llm:\n  model: repo\noidc:\n  issuer_url: \"\"\n  client_id: \"\"\nservices:\n  mapping:\n    enabled: false\n"
	if err := os.WriteFile(h.ConfigExample(), []byte(shipped), 0o600); err != nil {
		t.Fatal(err)
	}
	// What the user actually runs, with auth turned on by hand.
	edited := "llm:\n  model: anthropic/claude\n  model_list:\n    - model_name: fast\noidc:\n  issuer_url: https://login.example.com\n  client_id: kumoss\nservices:\n  mapping:\n    enabled: true\n"
	if err := os.WriteFile(h.ConfigYAML(), []byte(edited), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ComposeFile(), []byte("services:\n  core:\n    image: busybox\n  iac:\n    image: busybox\n  notifications:\n    image: busybox\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ComposeOverride(), []byte("services: {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := (&render.Env{}).Write(envPaths(h), saved.Copy()); err != nil {
		t.Fatal(err)
	}

	var shown string
	if err := RunConfig(context.Background(), ConfigOptions{
		Home:    h,
		Section: "git",
		UI:      stubSection{},
		Docker:  &stubDocker{},
		Confirm: func(diff string) (bool, error) { shown = diff; return true, nil },
		Warn:    io.Discard,
		Out:     io.Discard,
	}); err != nil {
		t.Fatalf("RunConfig: %v", err)
	}

	got, err := os.ReadFile(h.ConfigYAML())
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"issuer_url: https://login.example.com",
		"client_id: kumoss",
		"model_name: fast",
		"enabled: true",
	} {
		if !strings.Contains(string(got), want) {
			t.Errorf("config.yaml lost %q:\n%s", want, got)
		}
	}
	if strings.Contains(shown, "issuer_url") {
		t.Errorf("the preview claimed an oidc change:\n%s", shown)
	}
}

// localSamples must take its key set from the files on disk. A key the built-in
// fallback list does not know would otherwise be dropped by the next write.
func TestLocalSamplesKeepEveryKeyOnDisk(t *testing.T) {
	dir := t.TempDir()
	p := render.EnvPaths{
		Core:          filepath.Join(dir, "core.env"),
		IAC:           filepath.Join(dir, "iac.env"),
		Notifications: filepath.Join(dir, "notif.env"),
	}
	if err := os.WriteFile(p.Core, []byte("A=1\nHAND_ADDED_KEY=v\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	s := localSamples(p)
	if s.Core == nil || len(s.Core.Vars) != 2 {
		t.Fatalf("core sample = %+v, want the two keys on disk", s.Core)
	}
	if s.Core.Vars[1].Key != "HAND_ADDED_KEY" {
		t.Errorf("sample dropped the local key: %+v", s.Core.Vars)
	}
	// Values are dropped: they must not override what the state holds.
	for _, v := range s.Core.Vars {
		if v.Value != "" {
			t.Errorf("%s kept the sample value %q", v.Key, v.Value)
		}
	}
}

// Every secret value must be gone from the report, while the key survives so
// the user can tell which one changed.
func TestDiffReportMasksSecrets(t *testing.T) {
	before := "KUMOSS_IAC_TOKEN=aaaa\nGIT_USER=me\nKUMOSS_SQL_DATABASE_URL=postgres://u:hunter2@db/x\n"
	after := "KUMOSS_IAC_TOKEN=bbbb\nGIT_USER=you\nKUMOSS_SQL_DATABASE_URL=postgres://u:hunter2@db/x\n"

	got := diffReport([]fileDiff{{path: "core/.env", before: before, after: after}}, []string{"core"})

	for _, leaked := range []string{"aaaa", "bbbb", "hunter2"} {
		if strings.Contains(got, leaked) {
			t.Errorf("report leaks %q:\n%s", leaked, got)
		}
	}
	if !strings.Contains(got, "- GIT_USER=me") || !strings.Contains(got, "+ GIT_USER=you") {
		t.Errorf("report does not show the non-secret change:\n%s", got)
	}
	if !strings.Contains(got, "Recreate: [core]") {
		t.Errorf("report does not name the containers to recreate:\n%s", got)
	}
}

// A rotated secret must show that its key changed without showing either
// value, and a dropped key must show as a removal rather than vanish.
func TestDiffReportShowsSecretRotationAndRemovals(t *testing.T) {
	before := "KUMOSS_IAC_TOKEN=aaaa\nGIT_USER=me\nSLACK_WEBHOOK_URL=https://hooks/x\n"
	after := "KUMOSS_IAC_TOKEN=bbbb\nGIT_USER=me\n"

	got := diffReport([]fileDiff{{path: "core/.env", before: before, after: after}}, nil)

	for _, leaked := range []string{"aaaa", "bbbb", "hooks/x"} {
		if strings.Contains(got, leaked) {
			t.Errorf("report leaks %q:\n%s", leaked, got)
		}
	}
	for _, want := range []string{"- KUMOSS_IAC_TOKEN=" + maskValue, "+ KUMOSS_IAC_TOKEN=" + maskValue, "- SLACK_WEBHOOK_URL=" + maskValue} {
		if !strings.Contains(got, want) {
			t.Errorf("report does not show %q:\n%s", want, got)
		}
	}
}

// An untouched file is named, so "nothing changed" is visible rather than a
// blank screen.
func TestDiffReportNamesUnchangedFiles(t *testing.T) {
	got := diffReport([]fileDiff{{path: "kumoss.yaml", before: "a: 1\n", after: "a: 1\n"}}, nil)
	if !strings.Contains(got, "kumoss.yaml: unchanged") {
		t.Errorf("report = %q, want the unchanged file named", got)
	}
}

// The registry is the source of truth for the recreate table, so a wrong
// service name would silently recreate nothing.
func TestSectionsMapToTheContainersThatReadThem(t *testing.T) {
	want := map[string]string{
		"llm":           "core",
		"git":           "core",
		"cloud":         "iac",
		"engine":        "iac",
		"state":         "core iac",
		"notifications": "core notifications",
		"secrets":       "core iac notifications",
	}
	for name, services := range want {
		s := SectionByName(name)
		if s == nil {
			t.Errorf("section %q missing", name)
			continue
		}
		if got := strings.Join(s.Services, " "); got != services {
			t.Errorf("%s recreates %q, want %q", name, got, services)
		}
	}
	if len(Sections) != len(want) {
		t.Errorf("registry has %d sections, want %d", len(Sections), len(want))
	}
}

// A cloud edit that adds a credential file must also write the mount that
// carries it into the container. The env var pointed at a path that nothing
// mounted, and recreating the container could not fix a missing mount.
func TestConfigCloudEditWritesTheNewMount(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	for _, dir := range []string{h.ConfigDir(), h.CoreDir(), h.ServicesDir("iac"), h.ServicesDir("notifications")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	saved := &state.State{
		LLM:     state.LLM{Model: "anthropic/claude"},
		Git:     state.Git{Provider: "GITHUB"},
		Storage: state.Storage{Provider: "rustfs"},
	}
	if err := state.Save(h.StateFile(), saved); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ConfigYAML(), []byte("llm:\n  model: anthropic/claude\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ComposeFile(), []byte("services:\n  core:\n    image: busybox\n  iac:\n    image: busybox\n  notifications:\n    image: busybox\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	// The override init wrote: no mounts yet.
	if err := os.WriteFile(h.ComposeOverride(), []byte("services:\n  core:\n    image: busybox\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := (&render.Env{}).Write(envPaths(h), saved.Copy()); err != nil {
		t.Fatal(err)
	}

	var shown string
	if err := RunConfig(context.Background(), ConfigOptions{
		Home:    h,
		Section: "cloud",
		UI:      gcpKeySection{keyFile: "/keys/sa.json"},
		Docker:  &stubDocker{},
		Confirm: func(diff string) (bool, error) { shown = diff; return true, nil },
		Warn:    io.Discard,
		Out:     io.Discard,
	}); err != nil {
		t.Fatalf("RunConfig: %v", err)
	}

	override, err := os.ReadFile(h.ComposeOverride())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(override), "/keys") {
		t.Errorf("override has no mount for the new key file:\n%s", override)
	}
	if !strings.Contains(shown, "compose.override.yml") || strings.Contains(shown, "compose.override.yml: unchanged") {
		t.Errorf("the preview does not show the override change:\n%s", shown)
	}
}

// gcpKeySection adds a GCP key file in the cloud form, the edit the override
// has to carry as a mount.
type gcpKeySection struct {
	stubSection
	keyFile string
}

func (s gcpKeySection) Cloud(st *state.State) error {
	st.Cloud.GCP = &state.GCPAuth{Method: "file", KeyFile: s.keyFile}
	return nil
}

// An interrupted init can leave a home with no compose file. The edits are
// written first, so a compose call after them would fail on the missing file
// and report an error for a change that did land.
func TestConfigSkipsRecreateWithoutAComposeFile(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	for _, dir := range []string{h.ConfigDir(), h.CoreDir(), h.ServicesDir("iac"), h.ServicesDir("notifications")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	saved := &state.State{
		LLM:     state.LLM{Model: "anthropic/claude"},
		Git:     state.Git{Provider: "GITHUB"},
		Storage: state.Storage{Provider: "rustfs"},
	}
	if err := state.Save(h.StateFile(), saved); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ConfigYAML(), []byte("llm:\n  model: anthropic/claude\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := (&render.Env{}).Write(envPaths(h), saved.Copy()); err != nil {
		t.Fatal(err)
	}

	var out bytes.Buffer
	if err := RunConfig(context.Background(), ConfigOptions{
		Home:    h,
		Section: "git",
		UI:      stubSection{},
		Confirm: func(string) (bool, error) { return true, nil },
		Warn:    io.Discard,
		Out:     &out,
	}); err != nil {
		t.Fatalf("RunConfig: %v", err)
	}
	if !strings.Contains(out.String(), "recreated") {
		t.Errorf("RunConfig did not report the write: %q", out.String())
	}
}
