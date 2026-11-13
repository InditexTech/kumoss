// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"text/tabwriter"
	"time"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// StatusOptions is the resolved input to RunStatus.
type StatusOptions struct {
	Home home.Home
	// Compose is the stack. nil builds the real runner; tests inject a stub.
	Compose *docker.Compose
	// Probe hits the URLs below. nil uses a 3-second client.
	Probe *http.Client
	Out   io.Writer
}

// StatusURLs are the two probes: the core's unauthenticated auth config, which
// proves it is serving and not just up, and the sidecars' health endpoint.
const (
	coreConfigURL = "http://localhost:80/api/v1/auth/config"
	healthzPath   = "/healthz"
)

// RunStatus prints the stack table, the probes, the Kumoss tag and whether a
// generated file changed after its container was created.
func RunStatus(ctx context.Context, opts StatusOptions) error {
	out := opts.Out
	if out == nil {
		out = io.Discard
	}
	c := opts.Compose
	if c == nil {
		c = &docker.Compose{
			ProjectDir: opts.Home.Root,
			Files:      []string{rel(opts.Home.Root, opts.Home.ComposeFile()), rel(opts.Home.Root, opts.Home.ComposeOverride())},
		}
	}
	probe := opts.Probe
	if probe == nil {
		probe = &http.Client{Timeout: 3 * time.Second}
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

	printProbes(ctx, out, probe, rows)

	// Best effort: a missing state file is a half-written home, not a reason to
	// fail the whole report.
	s, err := state.Load(opts.Home.StateFile())
	if err == nil {
		printPendingRecreate(out, opts.Home, rows)
		printSkipped(out, s)
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
		fmt.Fprintf(tw, "%s\t%s\t%s\t%d\n", r.Service, state, uptimeOf(r.Status), r.Restart)
	}
	_ = tw.Flush()
}

// printProbes checks the core's auth config and each running sidecar's
// /healthz. Only reachable containers are probed: a stopped one has no answer
// worth waiting three seconds for.
func printProbes(ctx context.Context, w io.Writer, client *http.Client, rows []docker.PS) {
	fmt.Fprintln(w)
	if probe(ctx, client, coreConfigURL) {
		fmt.Fprintf(w, "core  %s  ok\n", coreConfigURL)
	} else {
		fmt.Fprintf(w, "core  %s  unreachable\n", coreConfigURL)
	}
	for _, r := range rows {
		if r.State != "running" || !sidecar(r.Service) {
			continue
		}
		url := "http://localhost:80/" + r.Service + healthzPath
		status := "unreachable"
		if probe(ctx, client, url) {
			status = "ok"
		}
		fmt.Fprintf(w, "%-8s %s  %s\n", r.Service, url, status)
	}
}

// probe reports whether url answers with 2xx.
func probe(ctx context.Context, client *http.Client, url string) bool {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	_ = resp.Body.Close()
	return resp.StatusCode >= 200 && resp.StatusCode < 300
}

// sidecar is true for the services nginx routes: they are the ones with a
// public /healthz. searxng and the databases are not part of the probe.
func sidecar(service string) bool {
	switch service {
	case "iac", "notifications", "mapping", "authz":
		return true
	}
	return false
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
	files := map[string][]string{
		h.ConfigYAML():                {"core"},
		h.CoreEnv():                   {"core"},
		h.ServiceEnv("iac"):           {"iac"},
		h.ServiceEnv("notifications"): {"notifications"},
	}
	// A changed mount block needs a recreate too, and the override is where it
	// lives.
	files[h.ComposeOverride()] = []string{"core", "iac"}

	created := map[string]time.Time{}
	for _, r := range rows {
		if r.Created > 0 {
			created[r.Service] = time.Unix(r.Created, 0)
		}
	}

	var pending []string
	for path, services := range files {
		info, err := os.Stat(path)
		if err != nil {
			continue
		}
		for _, svc := range services {
			if at, ok := created[svc]; ok && info.ModTime().After(at) {
				pending = append(pending, fmt.Sprintf("%s changed after %s was created", path, svc))
			}
		}
	}
	if len(pending) > 0 {
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
// feature reads as a choice rather than a bug.
func printSkipped(w io.Writer, s *state.State) {
	var skipped []string
	if !s.Notifications.Enabled {
		skipped = append(skipped, "notifications disabled")
	}
	for _, key := range tui.ProviderEnvKeys(s) {
		// Blank is only a skip for the optional credential variables.
		if optionalCredential(key) {
			continue
		}
		skipped = append(skipped, "llm credential not configured: "+key)
	}
	if len(skipped) > 0 {
		fmt.Fprintln(w)
		for _, line := range skipped {
			fmt.Fprintln(w, "skipped:", line)
		}
	}
}

// optionalCredential is true for the variables whose absence is a supported
// setup: Application Default Credentials, a location, a project id.
func optionalCredential(key string) bool {
	for _, part := range []string{"CREDENTIALS", "LOCATION", "PROJECT"} {
		if strings.Contains(key, part) {
			return true
		}
	}
	return false
}
