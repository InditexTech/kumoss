// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// compose emits one JSON object per line; a bad line must not hide the rest.
func TestParsePSReadsLineDelimitedJSON(t *testing.T) {
	rows := docker.ParsePS(`{"Service":"core","State":"running","Status":"Up 2 minutes (healthy)","Health":"healthy"}
{"Service":"iac","State":"exited","Status":"Exited (1) 1 minute ago"}`)
	if len(rows) != 2 {
		t.Fatalf("parsed %d rows, want 2", len(rows))
	}
	if rows[0].Service != "core" || rows[0].Health != "healthy" {
		t.Errorf("row 0 = %+v", rows[0])
	}
}

// The probe reads curl's -w status, not the body: a 500 is not ok.
func TestProbeRequiresA2xx(t *testing.T) {
	for _, c := range []struct {
		body string
		want bool
	}{
		{"200", true},
		{"204", true},
		{"500", false},
		{"404", false},
		{"", false},
	} {
		if got := probeReply(c.body); got != c.want {
			t.Errorf("probeReply(%q) = %v, want %v", c.body, got, c.want)
		}
	}
}

// The sidecars are not on the host: only nginx publishes a port and it forwards
// /api to core alone. A localhost/iac/healthz URL fell through to the web app's
// index.html, so every sidecar read as healthy whatever its state.
func TestProbeURLsStayInsideTheStack(t *testing.T) {
	if strings.Contains(coreConfigURL, "localhost") {
		t.Errorf("coreConfigURL = %q, must not go through the host", coreConfigURL)
	}
	url := fmt.Sprintf(healthzURL, "iac")
	if want := "http://iac:8080/healthz"; url != want {
		t.Errorf("sidecar URL = %q, want %q", url, want)
	}
	if strings.Contains(url, "localhost") {
		t.Errorf("sidecar URL %q goes through the host", url)
	}
}

// Uptime drops the health suffix the STATE column already carries.
func TestUptimeOfStripsHealth(t *testing.T) {
	if got := uptimeOf("Up 3 minutes (healthy)"); got != "Up 3 minutes" {
		t.Errorf("uptimeOf = %q", got)
	}
}

// One row per container, with state and health together.
func TestPrintServicesOneRowPerContainer(t *testing.T) {
	var b bytes.Buffer
	printServices(&b, []docker.PS{
		{Service: "core", State: "running", Status: "Up 3 minutes (healthy)", Health: "healthy"},
	})
	got := b.String()
	for _, want := range []string{"SERVICE", "STATE", "UPTIME", "core", "running/healthy", "Up 3 minute"} {
		if !strings.Contains(got, want) {
			t.Errorf("table missing %q:\n%s", want, got)
		}
	}
}

// The core row and the sidecar rows share one URL column: two different
// paddings left the core URL starting at a different offset.
func TestPrintProbesAlignsTheURLs(t *testing.T) {
	ok := func(context.Context, string) bool { return true }

	var b bytes.Buffer
	printProbes(t.Context(), &b, ok, []docker.PS{
		{Service: "core", State: "running"},
		{Service: "iac", State: "running"},
		{Service: "notifications", State: "running"},
	})

	var cols []int
	for _, line := range strings.Split(strings.TrimSpace(b.String()), "\n") {
		if i := strings.Index(line, "http://"); i >= 0 {
			cols = append(cols, i)
		}
	}
	if len(cols) != 3 {
		t.Fatalf("got %d URL rows, want 3:\n%s", len(cols), b.String())
	}
	for _, c := range cols {
		if c != cols[0] {
			t.Errorf("URL columns %v are not aligned:\n%s", cols, b.String())
		}
	}
}

// A configured install must not report its credentials as missing: the report
// read the key names only, so a working Anthropic setup always showed a skip.
func TestPrintSkippedReportsOnlyBlankCredentials(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	if err := os.MkdirAll(h.CoreDir(), 0o700); err != nil {
		t.Fatal(err)
	}
	s := &state.State{LLM: state.LLM{Provider: "anthropic"}}

	// Configured: nothing to report.
	if err := os.WriteFile(h.CoreEnv(), []byte("ANTHROPIC_API_KEY=sk-ant\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	printSkipped(&b, h, s)
	if strings.Contains(b.String(), "ANTHROPIC_API_KEY") {
		t.Errorf("configured key reported missing:\n%s", b.String())
	}

	// Blank: reported, with the fix the other checks name.
	if err := os.WriteFile(h.CoreEnv(), []byte("ANTHROPIC_API_KEY=\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	b.Reset()
	printSkipped(&b, h, s)
	if !strings.Contains(b.String(), "llm credential not configured: ANTHROPIC_API_KEY") {
		t.Errorf("blank key not reported:\n%s", b.String())
	}
}

// An optional credential (a blank is a supported setup) is never a skip, and
// the notifications line does not depend on the env file at all.
func TestPrintSkippedIgnoresOptionalCredentials(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	if err := os.MkdirAll(h.CoreDir(), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.CoreEnv(), []byte("VERTEXAI_CREDENTIALS=\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	printSkipped(&b, h, &state.State{LLM: state.LLM{Provider: "vertex_ai"}, Notifications: state.Notifications{Enabled: true}})
	if strings.Contains(b.String(), "VERTEXAI_CREDENTIALS") {
		t.Errorf("optional credential reported as a skip:\n%s", b.String())
	}
}
