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
	"os/exec"
	"strings"
)

// Runner is the seam the pipeline talks to. Tests stub it so no Docker daemon
// is needed; RunCompose is the real implementation.
type Runner interface {
	// Pull fetches every image the stack references that is not already
	// present, and returns how many it pulled.
	Pull(ctx context.Context) (int, error)
	// Up starts the stack detached. recreate makes compose replace containers
	// whose definition did not change, which is what picks up a new config.yaml
	// or .env (compose only compares the service definition, not mounted bytes).
	Up(ctx context.Context, recreate bool) error
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

// run executes docker compose in the project directory and returns its output.
// Output is captured rather than streamed: the commands are short and a failure
// needs its message attached to the error.
func (c *Compose) run(ctx context.Context, sub ...string) (string, error) {
	cmd := exec.CommandContext(ctx, "docker", c.args(sub...)...)
	cmd.Dir = c.ProjectDir
	out, err := cmd.CombinedOutput()
	if err != nil {
		return string(out), err
	}
	return string(out), nil
}

// Pull lists the stack's images, inspects each, and pulls only the missing ones.
// Compose has no "pull only what is absent" flag, so this is three calls. A
// re-run with every image present does no network work.
func (c *Compose) Pull(ctx context.Context) (int, error) {
	out, err := c.run(ctx, "config", "--images")
	if err != nil {
		return 0, err
	}
	pulled := 0
	for _, image := range strings.Fields(out) {
		// `docker image inspect` exits non-zero when the image is absent.
		if err := exec.CommandContext(ctx, "docker", "image", "inspect", image).Run(); err == nil {
			continue
		}
		if _, err := c.run(ctx, "pull", image); err != nil {
			return pulled, err
		}
		pulled++
	}
	return pulled, nil
}

// upArgs is Up's argument list, split out so the recreate decision is testable
// without a Docker daemon.
func upArgs(recreate bool) []string {
	if recreate {
		return []string{"up", "-d", "--force-recreate"}
	}
	return []string{"up", "-d"}
}

// Up starts the stack detached. recreate forces compose to replace containers
// even when their definition is unchanged: a rewritten config.yaml or .env is a
// mounted file, so compose sees no reason to act on its own.
func (c *Compose) Up(ctx context.Context, recreate bool) error {
	_, err := c.run(ctx, upArgs(recreate)...)
	return err
}
