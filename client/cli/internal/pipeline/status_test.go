// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/docker"
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

// The probe follows the answer, not the connection: a 500 is not ok.
func TestProbeRequiresA2xx(t *testing.T) {
	ok := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	defer ok.Close()
	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer bad.Close()

	if !probe(t.Context(), ok.Client(), ok.URL) {
		t.Error("a 200 was reported unreachable")
	}
	if probe(t.Context(), bad.Client(), bad.URL) {
		t.Error("a 500 was reported ok")
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
