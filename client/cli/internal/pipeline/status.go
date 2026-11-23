// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"context"
	"fmt"
	"io"
	"strings"
	"text/tabwriter"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// StatusOptions is the resolved input to RunStatus.
type StatusOptions struct {
	Home home.Home
	// Compose is the stack. nil builds the real runner; tests inject a stub.
	Compose *docker.Compose
	Out     io.Writer
}

// statusURLs are the probes: the core's unauthenticated auth config, which
// proves it is serving and not just up, and each sidecar's own health endpoint,
// by its compose service name. Only nginx is published on the host and it
// forwards /api to core alone, so a sidecar has no host address to probe: these
// are fetched from inside the stack.
const coreConfigURL = "http://core:8000/api/v1/auth/config"

// sidecarPort is the port each sidecar listens on, from its Dockerfile's
// EXPOSE and the compose file's expose. iac is 8082, not the 8080 the others
// use, so a single shared port made its probe read unreachable while it was
// serving.
var sidecarPort = map[string]int{
	"iac":           8082,
	"notifications": 8080,
}

// healthzURL is the probe for one sidecar, or "" for a service that serves no
// /healthz.
func healthzURL(service string) string {
	port, ok := sidecarPort[service]
	if !ok {
		return ""
	}
	return fmt.Sprintf("http://%s:%d/healthz", service, port)
}

// RunStatus prints the stack table, the probes, the Kumoss tag and whether a
// generated file changed after its container was created.
func RunStatus(ctx context.Context, opts StatusOptions) error {
	out := opts.Out
	if out == nil {
		out = io.Discard
	}
	c := opts.Compose
	if c == nil {
		c = docker.NewCompose(opts.Home)
	}

	fmt.Fprintf(out, "Kumoss %s (stack %s)\n\n", buildinfo.Version, buildinfo.KumossTag())

	rows, err := c.PS(ctx)
	if err != nil {
		return fmt.Errorf("docker compose ps: %w", err)
	}
	if len(rows) == 0 {
		fmt.Fprintln(out, "No containers. Run kumoss init.")
		return nil
	}
	printServices(out, rows)

	printProbes(ctx, out, c.Probe, rows)

	// Best effort: a missing state file is a half-written home, not a reason to
	// fail the whole report.
	s, err := state.Load(opts.Home.StateFile())
	if err == nil {
		printPendingRecreate(out, opts.Home, rows)
		printSkipped(out, opts.Home, s)
	}
	return nil
}

// printServices is the table: one line per container, with the state, how long
// it has been up and how often it restarted.
func printServices(w io.Writer, rows []docker.PS) {
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
	fmt.Fprintln(tw, "SERVICE\tSTATE\tUPTIME\tRESTARTS")
	for _, r := range rows {
		state := r.State
		if r.Health != "" {
			state += "/" + r.Health
		}
		fmt.Fprintf(tw, "%s\t%s\t%s\t%d\n", r.Service, state, uptimeOf(r.Status), r.RestartCount)
	}
	_ = tw.Flush()
}

// printProbes checks the core's auth config and each running sidecar's
// /healthz. Only reachable containers are probed: a stopped one has no answer
// worth waiting for. Tabwriter pads both the core row and the service rows, so
// the URLs line up in one column.
func printProbes(ctx context.Context, w io.Writer, probe func(context.Context, string) bool, rows []docker.PS) {
	fmt.Fprintln(w)
	tw := tabwriter.NewWriter(w, 0, 0, 2, ' ', 0)
	coreStatus := "unreachable"
	if probe(ctx, coreConfigURL) {
		coreStatus = "ok"
	}
	fmt.Fprintf(tw, "core\t%s\t%s\n", coreConfigURL, coreStatus)
	for _, r := range rows {
		url := healthzURL(r.Service)
		if r.State != "running" || url == "" {
			continue
		}
		status := "unreachable"
		if probe(ctx, url) {
			status = "ok"
		}
		fmt.Fprintf(tw, "%s\t%s\t%s\n", r.Service, url, status)
	}
	_ = tw.Flush()
}

// probeReply reads the status code curl printed with -w. Split from the command
// so the parsing is testable without a container.
func probeReply(out string) bool {
	code := strings.TrimSpace(out)
	return len(code) == 3 && strings.HasPrefix(code, "2")
}

// uptimeOf is the "Up 3 minutes" half of compose's Status, without the health
// suffix the STATE column already carries.
func uptimeOf(status string) string {
	if i := strings.Index(status, " ("); i > 0 {
		return strings.TrimSpace(status[:i])
	}
	return status
}

// printPendingRecreate names the generated files newer than the container that
// mounts them: compose compares the service definition, not the bytes of a
// mounted file, so those changes are not live yet.
func printPendingRecreate(w io.Writer, h home.Home, rows []docker.PS) {
	// Shared with kumoss run, which acts on the same list instead of
	// reporting it.
	if pending := staleFiles(h, rows); len(pending) > 0 {
		fmt.Fprintln(w)
		for _, line := range pending {
			fmt.Fprintln(w, "pending recreate:", line)
		}
		// A mount change alters the definition itself, so the container is
		// replaced rather than restarted.
		fmt.Fprintln(w, "run kumoss config cloud (or engine) to rewrite the mounts and recreate them")
	}
}

// printSkipped lists the optional pieces a run can leave unset, so a missing
// feature reads as a choice rather than a bug. A credential is only missing
// when its value in core/.env is blank: the keys alone say nothing, and
// reporting a configured install as skipped was the whole bug.
func printSkipped(w io.Writer, h home.Home, s *state.State) {
	var skipped []string
	if !s.Notifications.Enabled {
		skipped = append(skipped, "notifications disabled")
	}
	core := render.ReadEnv(h.CoreEnv())
	for _, key := range tui.RequiredEnvKeys(s) {
		if core[key] == "" {
			skipped = append(skipped, "llm credential not configured: "+key)
		}
	}
	if len(skipped) > 0 {
		fmt.Fprintln(w)
		for _, line := range skipped {
			fmt.Fprintln(w, "skipped:", line)
		}
	}
}
