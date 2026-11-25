// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"context"
	"fmt"
	"io"
	"os"
	"sort"
	"time"

	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// RunOptions is the resolved input to RunStack.
type RunOptions struct {
	Home home.Home
	// Docker is the stack. nil builds the real runner; tests inject a stub.
	Docker docker.Runner
	// Foreground keeps `up` attached: logs stream until Ctrl-C, which also
	// stops the stack.
	Foreground bool
	Out        io.Writer
}

// RunStack starts an already-configured stack. It writes nothing: the files
// are init's and config's to produce, and run only checks they agree with the
// recorded answers before handing the stack to compose.
func RunStack(ctx context.Context, opts RunOptions) error {
	out := opts.Out
	if out == nil {
		out = io.Discard
	}

	exists, err := state.StateFileExist(opts.Home.StateFile())
	if err != nil {
		return err
	}
	if !exists {
		// Without the recorded answers there is nothing to reconcile the
		// generated files against, so run cannot vouch for what it would start.
		return fmt.Errorf("no %s: run kumoss init first", opts.Home.StateFile())
	}
	s, err := state.Load(opts.Home.StateFile())
	if err != nil {
		return err
	}

	if problems := Preflight(opts.Home, s); len(problems) > 0 {
		printProblems(out, problems)
		return fmt.Errorf("%s", plural(len(problems), "problem", "problems")+" found; the stack was not started")
	}

	runner := opts.Docker
	if runner == nil {
		runner = docker.NewCompose(opts.Home)
	}

	rows, err := runner.PS(ctx)
	if err != nil {
		return fmt.Errorf("docker compose ps: %w", err)
	}

	// No containers means no images either, on a first run or after a down.
	// It is the only path that pays for a pull.
	if len(rows) == 0 {
		fmt.Fprintln(out, "No containers yet; pulling the images.")
		if err := runner.Pull(ctx); err != nil {
			return err
		}
		if err := runner.Up(ctx, false, !opts.Foreground); err != nil {
			return err
		}
		return started(out, s, opts.Foreground)
	}

	// Compose compares the service definition, not the bytes of a mounted
	// file, so an edited config.yaml or .env needs the containers replaced.
	stale := staleFiles(opts.Home, rows)
	for _, line := range stale {
		fmt.Fprintln(out, "recreating:", line)
	}
	if err := runner.Up(ctx, len(stale) > 0, !opts.Foreground); err != nil {
		return err
	}
	return started(out, s, opts.Foreground)
}

// started prints where the stack can be reached. Attached, the logs own the
// terminal until Ctrl-C, so there is no moment to print anything.
func started(out io.Writer, s *state.State, foreground bool) error {
	if foreground {
		return nil
	}
	_, err := fmt.Fprint(out, stackURLs(s))
	return err
}

// printProblems lists what blocks the run, each with the command that fixes
// it. Values are already masked by the checks that produced them.
func printProblems(w io.Writer, problems []Problem) {
	for _, p := range problems {
		fmt.Fprintln(w, "-", p.Message)
	}
	fmt.Fprintln(w)
	for _, fix := range fixes(problems) {
		fmt.Fprintln(w, "fix with:", fix)
	}
}

// fixes is the deduplicated command list, in the order the problems appeared,
// so two blank LLM variables do not print the same line twice.
func fixes(problems []Problem) []string {
	var out []string
	seen := map[string]bool{}
	for _, p := range problems {
		if p.Fix == "" || seen[p.Fix] {
			continue
		}
		seen[p.Fix] = true
		out = append(out, p.Fix)
	}
	return out
}

// plural renders a count with the right noun.
func plural(n int, one, many string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, one)
	}
	return fmt.Sprintf("%d %s", n, many)
}

// generatedFiles maps each generated file to the services that mount it. The
// override is listed for both: a rewritten mount block changes the definition
// of every service it touches.
func generatedFiles(h home.Home) map[string][]string {
	return map[string][]string{
		h.ConfigYAML():                {"core"},
		h.CoreEnv():                   {"core"},
		h.ServiceEnv("iac"):           {"iac"},
		h.ServiceEnv("notifications"): {"notifications"},
		// object-storage too: the override turns the console on and
		// publishes its port, so a rewrite changes that service as well.
		h.ComposeOverride():  {"core", "iac", "object-storage"},
		h.ObjectStorageEnv(): {"object-storage"},
	}
}

// staleFiles names the generated files newer than a container that mounts
// them, so the caller can replace those containers rather than start them.
// Sorted, or a map walk would reorder the report between runs.
func staleFiles(h home.Home, rows []docker.PS) []string {
	created := map[string]time.Time{}
	for _, r := range rows {
		if !r.CreatedAt.IsZero() {
			created[r.Service] = r.CreatedAt.Time
		}
	}
	var stale []string
	for path, services := range generatedFiles(h) {
		info, err := os.Stat(path)
		if err != nil {
			continue
		}
		for _, service := range services {
			if at, ok := created[service]; ok && info.ModTime().After(at) {
				stale = append(stale, fmt.Sprintf("%s changed after %s was created", path, service))
			}
		}
	}
	sort.Strings(stale)
	return stale
}
