// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package docker

import (
	"reflect"
	"testing"
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

// `docker compose pull` takes service names, never image references. Passing an
// image ref made compose fail with "no such service: <image>", which the
// pipeline reported as a bare "exit status 1" — the user saw nothing happen.
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

	// A reconfigure rewrote mounted files; compose compares the definition, so
	// only an explicit recreate picks them up.
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
