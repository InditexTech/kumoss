// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// A rewritten mount block changes the service definition, so the container has
// to be replaced, not just restarted. Anything that leaves the definition
// alone keeps the narrower recreate list.
func TestSameDefinitionFollowsTheMounts(t *testing.T) {
	h := home.Home{Root: "/home/u/.kumoss"}
	base := &state.State{Engine: state.Engine{Binary: "tofu"}}

	if !sameDefinition(h, base, base.Copy()) {
		t.Error("an unchanged state reported a different definition")
	}

	withKey := base.Copy()
	withKey.Cloud.GCP = &state.GCPAuth{Method: "file", KeyFile: "/keys/sa.json"}
	if sameDefinition(h, base, withKey) {
		t.Error("a new credential mount left the definition unchanged")
	}

	otherEngine := base.Copy()
	otherEngine.Engine.Binary = "terraform"
	if sameDefinition(h, base, otherEngine) {
		t.Error("a new IaC engine left the definition unchanged")
	}
}

// Every secret value must be gone from the report, while the key survives so
// the user can tell which one changed.
func TestDiffReportMasksSecrets(t *testing.T) {
	before := "KUMOSS_IAC_TOKEN=aaaa\nGIT_USER=me\nKUMOSS_SQL_DATABASE_URL=postgres://u:hunter2@db/x\n"
	after := "KUMOSS_IAC_TOKEN=bbbb\nGIT_USER=you\nKUMOSS_SQL_DATABASE_URL=postgres://u:hunter2@db/x\n"

	got := diffReport([]fileDiff{{path: "core/.env", before: before, after: after}}, []string{"core"})

	for _, leaked := range []string{"aaaa", "bbbb", "hunter2"} {
		if strings.Contains(got, leaked) {
			t.Errorf("report leaks %q:\n%s", leaked, got)
		}
	}
	if !strings.Contains(got, "- GIT_USER=me") || !strings.Contains(got, "+ GIT_USER=you") {
		t.Errorf("report does not show the non-secret change:\n%s", got)
	}
	if !strings.Contains(got, "Recreate: [core]") {
		t.Errorf("report does not name the containers to recreate:\n%s", got)
	}
}

// An untouched file is named, so "nothing changed" is visible rather than a
// blank screen.
func TestDiffReportNamesUnchangedFiles(t *testing.T) {
	got := diffReport([]fileDiff{{path: "kumoss.yaml", before: "a: 1\n", after: "a: 1\n"}}, nil)
	if !strings.Contains(got, "kumoss.yaml: unchanged") {
		t.Errorf("report = %q, want the unchanged file named", got)
	}
}

// The registry is the source of truth for the recreate table, so a wrong
// service name would silently recreate nothing.
func TestSectionsMapToTheContainersThatReadThem(t *testing.T) {
	want := map[string]string{
		"llm":           "core",
		"git":           "core",
		"cloud":         "iac",
		"engine":        "iac",
		"state":         "core iac",
		"notifications": "core notifications",
		"secrets":       "core iac notifications",
	}
	for name, services := range want {
		s := SectionByName(name)
		if s == nil {
			t.Errorf("section %q missing", name)
			continue
		}
		if got := strings.Join(s.Services, " "); got != services {
			t.Errorf("%s recreates %q, want %q", name, got, services)
		}
	}
	if len(Sections) != len(want) {
		t.Errorf("registry has %d sections, want %d", len(Sections), len(want))
	}
}
