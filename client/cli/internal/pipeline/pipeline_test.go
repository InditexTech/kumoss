// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// stubUI answers every question with a fixed value and records what it was
// asked, so a test can assert a prompt was or was not shown.
type stubUI struct {
	mode     tui.Mode
	regen    bool
	askedReg []string
}

func (s *stubUI) SelectStateAction() (tui.Mode, error)         { return s.mode, nil }
func (s *stubUI) Configure(tui.Mode, *state.State) error       { return nil }
func (s *stubUI) RotateSecrets([]tui.Secret) ([]string, error) { return nil, nil }
func (s *stubUI) ExtraVars([]tui.Secret) (map[string]string, error) {
	return map[string]string{}, nil
}
func (s *stubUI) ConfirmRegenerate(what string) (bool, error) {
	s.askedReg = append(s.askedReg, what)
	return s.regen, nil
}
func (s *stubUI) RunDocker() (bool, error) { return false, nil }

// stubDocker satisfies docker.Runner; the pipeline is never asked to start the
// stack in these tests.
type stubDocker struct{}

func (stubDocker) Pull(context.Context) error           { return nil }
func (stubDocker) Up(context.Context, bool, bool) error { return nil }

var _ docker.Runner = stubDocker{}

// install writes the files an existing install owns, so a run can be checked
// for touching them.
func install(t *testing.T) (home.Home, map[string]string) {
	t.Helper()
	h := home.Home{Root: t.TempDir()}
	files := map[string]string{
		h.StateFile():                 "schema_version: 1\nllm:\n  model: keep/me\n",
		h.ConfigYAML():                "# hand edited config\n",
		h.ComposeOverride():           "# hand edited override\n",
		h.CoreEnv():                   "KUMOSS_IAC_TOKEN=keep\n",
		h.ServiceEnv("iac"):           "KUMOSS_IAC_TOKEN=keep\n",
		h.ServiceEnv("notifications"): "KUMOSS_NOTIFICATIONS_TOKEN=keep\n",
	}
	for path, body := range files {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatalf("mkdir: %v", err)
		}
		if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
			t.Fatalf("write: %v", err)
		}
	}
	return h, files
}

// Keep it as is must write nothing: every file stays byte-identical, and the
// override is not even asked about.
func TestModeKeepLeavesEveryFileUntouched(t *testing.T) {
	h, files := install(t)
	ui := &stubUI{mode: tui.ModeKeep}

	opts := Options{
		Home:     h,
		UI:       ui,
		Docker:   stubDocker{},
		Download: &render.Download{Fetch: noFetch, Tag: "v1.0.0"},
	}
	if err := RunPipeline(context.Background(), opts); err != nil {
		t.Fatalf("RunPipeline: %v", err)
	}

	for path, want := range files {
		got, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read %s: %v", path, err)
		}
		if string(got) != want {
			t.Errorf("%s changed:\n got %q\nwant %q", path, got, want)
		}
	}
	if len(ui.askedReg) != 0 {
		t.Errorf("override prompt shown in ModeKeep: %v", ui.askedReg)
	}
}

// Reconfiguring an existing install asks before replacing a hand-edited
// override, and a "no" answer leaves it alone.
func TestReconfigureAsksBeforeOverwritingTheOverride(t *testing.T) {
	h, files := install(t)
	ui := &stubUI{mode: tui.ModeReconfigure, regen: false}

	opts := Options{
		Home:      h,
		UI:        ui,
		Docker:    stubDocker{},
		Download:  &render.Download{Fetch: noFetch, Tag: "v1.0.0"},
		HostCerts: true,
	}
	if err := RunPipeline(context.Background(), opts); err != nil {
		t.Fatalf("RunPipeline: %v", err)
	}

	if len(ui.askedReg) != 1 || ui.askedReg[0] != "compose.override.yml" {
		t.Fatalf("override prompt = %v, want one for compose.override.yml", ui.askedReg)
	}
	got, err := os.ReadFile(h.ComposeOverride())
	if err != nil {
		t.Fatalf("read override: %v", err)
	}
	if string(got) != files[h.ComposeOverride()] {
		t.Errorf("override rewritten despite declining: %q", got)
	}
}

// noFetch answers only the two files the pipeline needs before it reaches the
// override: the compose file (fetched before the mode is known) and the default
// config.yaml (rendered on reconfigure). Everything else fails, which keeps the
// test offline. The sample fetch failure is a warning, not an error.
func noFetch(_ context.Context, _, path string) ([]byte, error) {
	switch path {
	case "docker-compose.yml":
		return []byte("services: {}\n"), nil
	case "config.yaml":
		return []byte("llm:\n  model: repo/default\n"), nil
	}
	return nil, os.ErrNotExist
}
