// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package docker runs the `docker compose` commands that start the stack. The
// CLI always invokes compose with an explicit -f list, so the compose file in
// src/ is the only one that loads: compose would otherwise pick up any
// docker-compose.override.yml sitting next to it and change the stack under the
// user. The project name comes from the compose file itself (`name: kumoss`), so
// volume names stay kumoss_workspaces and match the documentation.
package docker

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// Runner is the seam the pipeline talks to. Tests stub it so no Docker daemon
// is needed; Compose is the real implementation.
type Runner interface {
	// Pull fetches every image the stack references that is not already
	// present. A re-run with every image present does no network work.
	// Progress streams to the terminal: a large pull is otherwise a silent
	// wait. Returns only an error; the pulled count is not reported.
	Pull(ctx context.Context) error
	// Up starts the stack. detach runs it in the background; otherwise compose
	// stays in the foreground and streams logs until the context is cancelled.
	// recreate replaces containers whose definition did not change, which is
	// what picks up a new config.yaml or .env (compose only compares the
	// service definition, not mounted bytes).
	Up(ctx context.Context, recreate, detach bool) error
}

// Compose is the real Runner. It shells out to `docker compose`.
type Compose struct {
	// ProjectDir is the compose project directory (the home root). Paths inside
	// compose.override.yml resolve against the override file's own directory,
	// which is here.
	ProjectDir string
	// Files are the -f arguments, in order: the downloaded docker-compose.yml
	// then the generated compose.override.yml. Relative to ProjectDir.
	Files []string
}

var _ Runner = (*Compose)(nil) // compile-time check that Compose satisfies Runner

// args builds the command line shared by every call. The explicit -f list is
// what stops a stray docker-compose.override.yml from loading.
func (c *Compose) args(sub ...string) []string {
	args := []string{"compose"}
	for _, f := range c.Files {
		args = append(args, "-f", f)
	}
	return append(args, sub...)
}

// run executes docker compose in the project directory and captures its
// combined output. Only the detached Up uses it, which is short; anything
// long-running goes through stream. On failure the output is wrapped into the
// error — `exit status 1` alone tells the user nothing, which reads as
// "nothing happened".
func (c *Compose) run(ctx context.Context, sub ...string) (string, error) {
	cmd := exec.CommandContext(ctx, "docker", c.args(sub...)...)
	cmd.Dir = c.ProjectDir
	out, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if msg == "" {
			return "", fmt.Errorf("docker compose %s: %w", sub[0], err)
		}
		return string(out), fmt.Errorf("docker compose %s: %w\n%s", sub[0], err, msg)
	}
	return string(out), nil
}

// pullArgs is Pull's argument list, split out so it is testable without a
// Docker daemon. It takes no image: `pull` resolves services from the compose
// file itself.
func pullArgs() []string {
	return []string{"pull", "--policy", "missing"}
}

// stream runs docker compose with its output attached to this process, so a
// long-running command shows its progress as it arrives instead of nothing
// until it exits. Both stdout and stderr go to this process's stderr, which is
// where logs belong. Used by Pull and by Up when not detached.
func (c *Compose) stream(ctx context.Context, sub ...string) error {
	cmd := exec.CommandContext(ctx, "docker", c.args(sub...)...)
	cmd.Dir = c.ProjectDir
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// Pull fetches the images the stack needs that are not already present.
// `--policy missing` is compose's own "pull only what is absent", so a re-run
// with every image present does no network work and there is no image/service
// name juggling to get wrong: `pull` takes service names, not image references.
// Output is streamed rather than captured: the user should see which images are
// being downloaded. compose sends progress to stderr, which is what stream uses.
func (c *Compose) Pull(ctx context.Context) error {
	return c.stream(ctx, pullArgs()...)
}

// upArgs is Up's argument list, split out so the recreate and detach decisions
// are testable without a Docker daemon.
func upArgs(recreate, detach bool) []string {
	args := []string{"up"}
	if detach {
		args = append(args, "-d")
	}
	if recreate {
		args = append(args, "--force-recreate")
	}
	return args
}

// Up starts the stack. detach runs it in the background; without it compose
// stays in the foreground and streams every container's logs until the context
// is cancelled (Ctrl-C), which also stops the stack. recreate forces compose to
// replace containers even when their definition is unchanged: a rewritten
// config.yaml or .env is a mounted file, so compose sees no reason to act on its
// own.
func (c *Compose) Up(ctx context.Context, recreate, detach bool) error {
	args := upArgs(recreate, detach)
	if detach {
		_, err := c.run(ctx, args...)
		return err
	}
	// Foreground: stream rather than buffer, or the user sees nothing until
	// Ctrl-C. Stdout and stderr both go to this process's stderr, which is
	// where logs belong.
	return c.stream(ctx, args...)
}
