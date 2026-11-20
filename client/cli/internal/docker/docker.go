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
	"path/filepath"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
)

// Runner is the seam the pipeline talks to; tests stub it, Compose implements
// it for real.
type Runner interface {
	// PS lists the stack's containers, including the stopped ones, so a
	// caller can tell an empty home from a stack that merely exited.
	PS(ctx context.Context) ([]PS, error)
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
	// ProjectName is passed as -p, overriding the `name:` the downloaded
	// compose file fixes. Without it every home is the same project, so a
	// second home reconfigures the first one's containers and shares its
	// volumes.
	ProjectName string
	// Files are the -f arguments in order, relative to ProjectDir: the
	// downloaded compose file, then the generated override.
	Files []string
}

var _ Runner = (*Compose)(nil) // compile-time check that Compose satisfies Runner

// NewCompose builds the runner for one home, so no caller can forget the
// project name and silently share another home's stack. Only the -f files that
// exist are passed: compose fails on a missing one, and an interrupted init
// leaves src/docker-compose.yml without the override. The project name is
// derived from the root, so a partial home still addresses its own stack.
func NewCompose(h home.Home) *Compose {
	files := []string{h.ComposeFile(), h.ComposeOverride()}
	existing := make([]string, 0, len(files))
	for _, f := range files {
		if _, err := os.Stat(f); err == nil {
			existing = append(existing, rel(h.Root, f))
		}
	}
	return &Compose{
		ProjectDir:  h.Root,
		ProjectName: h.ProjectName(),
		Files:       existing,
	}
}

// args builds the command line shared by every call.
func (c *Compose) args(sub ...string) []string {
	args := []string{"compose"}
	if c.ProjectName != "" {
		args = append(args, "-p", c.ProjectName)
	}
	for _, f := range c.Files {
		args = append(args, "-f", f)
	}
	return append(args, sub...)
}

// rel makes path relative to base for the -f arguments. Absolute would work
// too; relative keeps the command line readable.
func rel(base, path string) string {
	if r, err := filepath.Rel(base, path); err == nil {
		return r
	}
	return path
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
// takes effect. `restart` would keep the old environment, and plain `up` would
// keep the container too: compose compares the service definition, not the
// bytes of a mounted file, so a config.yaml-only change looks like no change.
// The caller only names the services whose files changed, so forcing every
// named one costs nothing else.
func (c *Compose) Recreate(ctx context.Context, services ...string) error {
	args := append([]string{"up", "-d", "--force-recreate"}, services...)
	_, err := c.run(ctx, args...)
	return err
}

// Probe fetches url from inside the stack and reports whether it answered 2xx.
// Only the proxy publishes a port, and it forwards /api to core alone, so a
// sidecar has no address on the host: a URL like localhost/iac/healthz fell
// through to the web app's index.html and every sidecar read as healthy.
// The proxy image is Debian with curl and no wget; when it is not on the
// stack's network nothing resolves and every probe reads unreachable.
func (c *Compose) Probe(ctx context.Context, url string) bool {
	out, err := c.run(ctx, "exec", "-T", "proxy", "curl", "-fsS", "-o", "/dev/null", "-w", "%{http_code}", url)
	if err != nil {
		return false
	}
	// -w prints the status last; -f already failed on anything 4xx/5xx.
	code := strings.TrimSpace(out)
	return len(code) == 3 && strings.HasPrefix(code, "2")
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
