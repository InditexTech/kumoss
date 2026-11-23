// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// recordingDocker records what the stack was asked to do, so a test can assert
// on the decision rather than on docker's output.
type recordingDocker struct {
	rows     []docker.PS
	psErr    error
	pulled   bool
	upCalls  int
	recreate bool
	detach   bool
}

func (r *recordingDocker) PS(context.Context) ([]docker.PS, error) { return r.rows, r.psErr }
func (r *recordingDocker) Pull(context.Context) error              { r.pulled = true; return nil }
func (r *recordingDocker) Up(_ context.Context, recreate, detach bool) error {
	r.upCalls++
	r.recreate = recreate
	r.detach = detach
	return nil
}

func (r *recordingDocker) Recreate(context.Context, ...string) error { return nil }

var _ docker.Runner = (*recordingDocker)(nil)

// runnable is configured() plus a kumoss.yaml on disk, so RunStack can load
// the state the preflight reconciles against.
func runnable(t *testing.T) (opts RunOptions, rec *recordingDocker) {
	t.Helper()
	h, s := configured(t)
	if err := state.Save(h.StateFile(), s); err != nil {
		t.Fatalf("Save: %v", err)
	}
	rec = &recordingDocker{}
	return RunOptions{Home: h, Docker: rec, Out: &strings.Builder{}}, rec
}

// container is a ps row created at the given time.
func container(service string, created time.Time) docker.PS {
	return docker.PS{Service: service, State: "running", CreatedAt: created}
}

// Without kumoss.yaml there is nothing to reconcile the files against, so run
// cannot vouch for the stack it would start.
func TestRunStackRefusesWithoutAStateFile(t *testing.T) {
	opts, rec := runnable(t)
	if err := os.Remove(opts.Home.StateFile()); err != nil {
		t.Fatalf("remove: %v", err)
	}

	err := RunStack(context.Background(), opts)

	if err == nil {
		t.Fatal("a home with no kumoss.yaml started the stack")
	}
	if !strings.Contains(err.Error(), "kumoss init") {
		t.Errorf("the error does not point at init: %v", err)
	}
	if rec.upCalls != 0 || rec.pulled {
		t.Error("docker was called despite the missing state file")
	}
}

// A problem the preflight found must stop the run: starting anyway is how a
// stack boots on credentials nobody configured.
func TestRunStackStopsOnAPreflightProblem(t *testing.T) {
	opts, rec := runnable(t)
	write(t, opts.Home.CoreEnv(), "ANTHROPIC_API_KEY=\nKUMOSS_IAC_TOKEN=shared-iac\n")
	out := &strings.Builder{}
	opts.Out = out

	err := RunStack(context.Background(), opts)

	if err == nil {
		t.Fatal("a blank credential started the stack")
	}
	if !strings.Contains(out.String(), "ANTHROPIC_API_KEY") {
		t.Errorf("the blank variable was not printed:\n%s", out)
	}
	if !strings.Contains(out.String(), "kumoss config llm") {
		t.Errorf("the fix was not printed:\n%s", out)
	}
	if rec.upCalls != 0 || rec.pulled {
		t.Error("docker was called despite a preflight problem")
	}
}

// Nothing to start means the images may be missing too; it is the only path
// that pays for a pull.
func TestRunStackPullsOnlyWhenThereAreNoContainers(t *testing.T) {
	opts, rec := runnable(t)
	rec.rows = nil

	if err := RunStack(context.Background(), opts); err != nil {
		t.Fatalf("RunStack: %v", err)
	}

	if !rec.pulled {
		t.Error("an empty stack was started without pulling the images")
	}
	if rec.upCalls != 1 || rec.recreate {
		t.Errorf("up calls = %d, recreate = %v; want one plain up", rec.upCalls, rec.recreate)
	}
	if !rec.detach {
		t.Error("the default run did not detach")
	}
}

// Containers already there means the images are there, so a pull is network
// work for nothing.
func TestRunStackSkipsThePullWhenContainersExist(t *testing.T) {
	opts, rec := runnable(t)
	rec.rows = []docker.PS{container("core", time.Now().Add(time.Hour))}

	if err := RunStack(context.Background(), opts); err != nil {
		t.Fatalf("RunStack: %v", err)
	}

	if rec.pulled {
		t.Error("an existing stack was pulled again")
	}
	if rec.upCalls != 1 || rec.recreate {
		t.Errorf("up calls = %d, recreate = %v; want one plain up", rec.upCalls, rec.recreate)
	}
}

// Compose compares the service definition, not the bytes of a mounted file,
// so a plain up would keep the old values and the edit would silently do
// nothing.
func TestRunStackRecreatesWhenAGeneratedFileIsNewerThanItsContainer(t *testing.T) {
	opts, rec := runnable(t)
	rec.rows = []docker.PS{container("core", time.Now().Add(-time.Hour))}
	// Rewritten now, so it postdates the container above.
	write(t, opts.Home.ConfigYAML(), configuredConfigYAML)

	if err := RunStack(context.Background(), opts); err != nil {
		t.Fatalf("RunStack: %v", err)
	}

	if !rec.recreate {
		t.Error("an edited config.yaml did not force a recreate")
	}
}

// --foreground streams the logs instead of backgrounding the stack.
func TestRunStackStaysAttachedInForeground(t *testing.T) {
	opts, rec := runnable(t)
	opts.Foreground = true

	if err := RunStack(context.Background(), opts); err != nil {
		t.Fatalf("RunStack: %v", err)
	}

	if rec.detach {
		t.Error("--foreground detached anyway")
	}
}
