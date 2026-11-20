// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package docker

import (
	"os"
	"reflect"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
)

func TestArgsUseAnExplicitFileList(t *testing.T) {
	c := &Compose{
		ProjectDir: "/home/u/.kumoss",
		Files:      []string{"src/docker-compose.yml", "compose.override.yml"},
	}
	got := c.args("up", "-d")
	want := []string{
		"compose",
		"-f", "src/docker-compose.yml",
		"-f", "compose.override.yml",
		"up", "-d",
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("args = %v, want %v", got, want)
	}
}

// `pull` takes service names, never image refs: passing one failed with "no
// such service", which surfaced as a bare "exit status 1".
func TestPullUsesTheMissingPolicy(t *testing.T) {
	got := pullArgs()
	want := []string{"pull", "--policy", "missing"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("pull args = %v, want %v", got, want)
	}
}

func TestUpForcesRecreateOnlyWhenAsked(t *testing.T) {
	// A fresh install has nothing to replace.
	if got := upArgs(false, true); !reflect.DeepEqual(got, []string{"up", "-d"}) {
		t.Errorf("fresh up args = %v, want no --force-recreate", got)
	}

	// Compose compares the definition, so only a recreate picks up new bytes.
	if got := upArgs(true, true); !reflect.DeepEqual(got, []string{"up", "-d", "--force-recreate"}) {
		t.Errorf("reconfigure up args = %v, want --force-recreate", got)
	}
}

// Foreground mode drops -d, so compose streams logs instead of exiting at once.
func TestUpForegroundDropsDetach(t *testing.T) {
	if got := upArgs(false, false); !reflect.DeepEqual(got, []string{"up"}) {
		t.Errorf("foreground up args = %v, want no -d", got)
	}
	if got := upArgs(true, false); !reflect.DeepEqual(got, []string{"up", "--force-recreate"}) {
		t.Errorf("foreground recreate args = %v, want no -d", got)
	}
}

// Without -p the downloaded file's `name: kumoss` wins and every home is the
// same project.
func TestArgsPassTheProjectName(t *testing.T) {
	c := &Compose{
		ProjectDir:  "/home/u/lab",
		ProjectName: "kumoss-abcd1234",
		Files:       []string{"src/docker-compose.yml"},
	}
	got := c.args("down", "-v")
	want := []string{
		"compose",
		"-p", "kumoss-abcd1234",
		"-f", "src/docker-compose.yml",
		"down", "-v",
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("args = %v, want %v", got, want)
	}
}

// An interrupted init can leave src/docker-compose.yml without the override.
// compose fails on a -f that does not exist, so only the present files are
// passed; the project name still comes from the root, so the stack is found.
func TestNewComposePassesOnlyExistingFiles(t *testing.T) {
	h := home.Home{Root: t.TempDir()}

	// Nothing written yet: no -f at all, but still this home's project.
	c := NewCompose(h)
	if len(c.Files) != 0 {
		t.Errorf("Files = %v, want none for an empty home", c.Files)
	}
	if c.ProjectName != h.ProjectName() {
		t.Errorf("project = %q, want %q", c.ProjectName, h.ProjectName())
	}

	// The compose file alone: it is passed, the missing override is not.
	if err := os.MkdirAll(h.SrcDir(), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.ComposeFile(), []byte("services: {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	c = NewCompose(h)
	if len(c.Files) != 1 || c.Files[0] != "src/docker-compose.yml" {
		t.Errorf("Files = %v, want only src/docker-compose.yml", c.Files)
	}

	// Both: the full list, in the order compose merges them.
	if err := os.WriteFile(h.ComposeOverride(), []byte("services: {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	c = NewCompose(h)
	want := []string{"src/docker-compose.yml", "compose.override.yml"}
	if len(c.Files) != 2 || c.Files[0] != want[0] || c.Files[1] != want[1] {
		t.Errorf("Files = %v, want %v", c.Files, want)
	}
}

func TestNewComposeCarriesTheHomeProject(t *testing.T) {
	h := home.Home{Root: t.TempDir()}
	c := NewCompose(h)
	if c.ProjectDir != h.Root || c.ProjectName != h.ProjectName() {
		t.Errorf("NewCompose = %+v, want root %q and project %q", c, h.Root, h.ProjectName())
	}
}
