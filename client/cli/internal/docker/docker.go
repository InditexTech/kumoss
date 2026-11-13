// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package docker runs the `docker compose` commands that start the stack.
// Always with an explicit -f list, or compose would also load any stray
// docker-compose.override.yml and change the stack under the user. The project
// name comes from the compose file itself, so volumes stay kumoss_*.
package docker

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// Runner is the seam the pipeline talks to; tests stub it, Compose implements
// it for real.
type Runner interface {
	// Pull fetches the images that are missing, streaming progress — a large
	// pull is otherwise a silent wait. A re-run does no network work.
	Pull(ctx context.Context) error
	// Up starts the stack. detach backgrounds it; otherwise logs stream until
	// the context is cancelled. recreate replaces containers whose definition
	// did not change, which is what picks up a rewritten config.yaml or .env.
	Up(ctx context.Context, recreate, detach bool) error
}

// Compose is the real Runner. It shells out to `docker compose`.
type Compose struct {
	// ProjectDir is the working directory for the command (the home root).
	// Relative paths inside both files resolve against the FIRST -f file's
	// directory, src/ — not against this.
	ProjectDir string
	// Files are the -f arguments in order, relative to ProjectDir: the
	// downloaded compose file, then the generated override.
	Files []string
}

var _ Runner = (*Compose)(nil) // compile-time check that Compose satisfies Runner

// args builds the command line shared by every call.
func (c *Compose) args(sub ...string) []string {
	args := []string{"compose"}
	for _, f := range c.Files {
		args = append(args, "-f", f)
	}
	return append(args, sub...)
}

// run captures combined output; only the short detached Up uses it. On failure
// the output is wrapped into the error, since `exit status 1` alone reads as
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

// pullArgs is split out so it is testable without a daemon.
func pullArgs() []string {
	return []string{"pull", "--policy", "missing"}
}

// stream attaches the output to this process so progress arrives as it
// happens. Both streams go to stderr, which is where logs belong.
func (c *Compose) stream(ctx context.Context, sub ...string) error {
	cmd := exec.CommandContext(ctx, "docker", c.args(sub...)...)
	cmd.Dir = c.ProjectDir
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// Recreate replaces the named services so a rewritten .env or mounted file
// takes effect. `restart` would keep the old environment.
func (c *Compose) Recreate(ctx context.Context, services ...string) error {
	args := append([]string{"up", "-d"}, services...)
	_, err := c.run(ctx, args...)
	return err
}

// Logs streams the containers' logs. follow keeps reading until the context is
// cancelled; since is passed through to compose, which understands 30m and a
// timestamp.
func (c *Compose) Logs(ctx context.Context, follow bool, since string, services ...string) error {
	args := []string{"logs"}
	if follow {
		args = append(args, "-f")
	}
	if since != "" {
		args = append(args, "--since", since)
	}
	return c.stream(ctx, append(args, services...)...)
}

// Down stops and removes the stack: containers, network, and with volumes the
// data. Volumes outlive a plain down, so the next init would find the old
// database and the old administrator.
func (c *Compose) Down(ctx context.Context, volumes bool) error {
	args := []string{"down"}
	if volumes {
		args = append(args, "-v")
	}
	return c.stream(ctx, args...)
}

// Pull fetches the missing images. `--policy missing` is compose's own "only
// what is absent", so a re-run does no network work and there are no service
// names to get wrong.
func (c *Compose) Pull(ctx context.Context) error {
	return c.stream(ctx, pullArgs()...)
}

// upArgs is split out so the recreate and detach decisions are testable.
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

// Up starts the stack. Without detach it stays in the foreground until the
// context is cancelled, which also stops the stack. recreate forces compose to
// replace containers whose definition is unchanged: a rewritten config.yaml or
// .env is a mounted file, so compose sees no reason to act on its own.
func (c *Compose) Up(ctx context.Context, recreate, detach bool) error {
	args := upArgs(recreate, detach)
	if detach {
		_, err := c.run(ctx, args...)
		return err
	}
	// Stream rather than buffer, or the user sees nothing until Ctrl-C.
	return c.stream(ctx, args...)
}
