// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
)

// fakeTooling stubs the commands doctor runs. missing lists the binaries that
// are not on PATH; versions maps a command line to its output.
func fakeTooling(missing []string, versions map[string]string) (func(string) (string, error), func(context.Context, string, ...string) (string, error)) {
	lookPath := func(name string) (string, error) {
		for _, m := range missing {
			if m == name {
				return "", errors.New("not found")
			}
		}
		return "/usr/bin/" + name, nil
	}
	output := func(_ context.Context, name string, args ...string) (string, error) {
		key := strings.TrimSpace(name + " " + strings.Join(args, " "))
		if v, ok := versions[key]; ok {
			if v == "" {
				return "", errors.New("exit status 1")
			}
			return v, nil
		}
		return "", errors.New("unexpected command: " + key)
	}
	return lookPath, output
}

// doctorHome is a temp home with no kumoss.yaml: a machine that never ran init.
func doctorHome(t *testing.T) home.Home {
	t.Helper()
	return home.Home{Root: filepath.Join(t.TempDir(), "kumoss")}
}

// A missing home names the command that creates it, but only when the root
// was chosen: the default needs none. The flag is hidden, so the hint uses
// KUMOSS_HOME, the supported way to pick another home.
func TestInitHintNamesTheEnvVarUnlessDefault(t *testing.T) {
	h := home.Home{Root: "/home/me/.kumoss_copy_2"}
	cases := []struct {
		src  home.Source
		want string
	}{
		{home.SourceDefault, "Run kumoss init."},
		{home.SourceFlag, "Run KUMOSS_HOME=/home/me/.kumoss_copy_2 kumoss init to install into this home."},
		{home.SourceEnv, "Run KUMOSS_HOME=/home/me/.kumoss_copy_2 kumoss init to install into this home."},
		{home.SourcePointer, "Run KUMOSS_HOME=/home/me/.kumoss_copy_2 kumoss init to install into this home."},
	}
	for _, c := range cases {
		if got := initHint(h, c.src); got != c.want {
			t.Errorf("initHint(%v) = %q, want %q", c.src, got, c.want)
		}
	}
}

// The hint reaches the report, not just the helper.
func TestDoctorPointsAtInitWithTheHomeEnvVar(t *testing.T) {
	h := doctorHome(t)
	lookPath, output := fakeTooling(nil, map[string]string{
		"docker --version":                        "Docker version 27.1.1\n",
		"docker compose version --short":          "2.29.1\n",
		"docker info --format {{.ServerVersion}}": "27.1.1\n",
	})
	var b bytes.Buffer
	_ = RunDoctor(t.Context(), DoctorOptions{
		Home: h, Source: home.SourceFlag, LookPath: lookPath, Output: output, Out: &b,
	})
	if !strings.Contains(b.String(), "KUMOSS_HOME="+h.Root) {
		t.Errorf("report does not name KUMOSS_HOME:\n%s", b.String())
	}
}

// doctor reports; it must not create the home. A typo'd --home used to leave an
// empty directory behind.
func TestDoctorCreatesNothing(t *testing.T) {
	h := doctorHome(t) // a root under t.TempDir() that does not exist yet
	lookPath, output := fakeTooling(nil, map[string]string{
		"docker --version":                        "Docker version 27.1.1\n",
		"docker compose version --short":          "2.29.1\n",
		"docker info --format {{.ServerVersion}}": "27.1.1\n",
	})
	var b bytes.Buffer
	_ = RunDoctor(t.Context(), DoctorOptions{
		Home: h, LookPath: lookPath, Output: output, Out: &b,
	})

	if _, err := os.Stat(h.Root); !os.IsNotExist(err) {
		t.Errorf("doctor created %s (err=%v):\n%s", h.Root, err, b.String())
	}
	if !strings.Contains(b.String(), "does not exist yet") {
		t.Errorf("missing home not reported:\n%s", b.String())
	}
	// Nothing may be left in the parent either.
	entries, err := os.ReadDir(filepath.Dir(h.Root))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Errorf("doctor left files behind: %v", entries)
	}
}

// A read-only parent means init could not write the home.
func TestDoctorRejectsAReadOnlyHome(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0o500); err != nil {
		t.Skipf("cannot chmod: %v", err)
	}
	t.Cleanup(func() { _ = os.Chmod(root, 0o700) })

	got := checkHome(home.Home{Root: filepath.Join(root, "kumoss")})
	if got.OK {
		t.Errorf("a read-only parent passed: %+v", got)
	}
}

// A missing docker names itself and does not stop the other checks.
func TestDoctorReportsEveryCheck(t *testing.T) {
	var b bytes.Buffer
	lookPath, output := fakeTooling([]string{"docker"}, nil)
	err := RunDoctor(t.Context(), DoctorOptions{
		Home: doctorHome(t), LookPath: lookPath, Output: output, Out: &b,
	})
	if err == nil {
		t.Error("doctor passed with no docker installed")
	}
	got := b.String()
	for _, want := range []string{"docker", "docker compose", "docker daemon", "home", "FAIL"} {
		if !strings.Contains(got, want) {
			t.Errorf("report missing %q:\n%s", want, got)
		}
	}
	// The home is still checked and reported, or one failure hides the rest.
	if !strings.Contains(got, "ok   home") {
		t.Errorf("home was not checked:\n%s", got)
	}
}

// A healthy machine with no install is a pass, and points at init.
func TestDoctorPassesWithoutAnInstall(t *testing.T) {
	var b bytes.Buffer
	lookPath, output := fakeTooling(nil, map[string]string{
		"docker --version":                        "Docker version 27.1.1, build abc\n",
		"docker compose version --short":          "v2.29.1\n",
		"docker info --format {{.ServerVersion}}": "27.1.1\n",
	})
	if err := RunDoctor(t.Context(), DoctorOptions{
		Home: doctorHome(t), LookPath: lookPath, Output: output, Out: &b,
	}); err != nil {
		t.Fatalf("doctor failed on a healthy machine: %v\n%s", err, b.String())
	}
	if !strings.Contains(b.String(), "kumoss init") {
		t.Errorf("no install did not point at init:\n%s", b.String())
	}
}

// Compose v1 is rejected: it lacks the flags run and status pass.
func TestDoctorRejectsComposeV1(t *testing.T) {
	var b bytes.Buffer
	lookPath, output := fakeTooling(nil, map[string]string{
		"docker --version":                        "Docker version 20.10.0\n",
		"docker compose version --short":          "",
		"docker compose version":                  "docker-compose version 1.29.2\n",
		"docker info --format {{.ServerVersion}}": "20.10.0\n",
	})
	err := RunDoctor(t.Context(), DoctorOptions{
		Home: doctorHome(t), LookPath: lookPath, Output: output, Out: &b,
	})
	if err == nil {
		t.Error("doctor passed without compose v2")
	}
	if !strings.Contains(b.String(), "v1 found") {
		t.Errorf("compose v1 was not explained:\n%s", b.String())
	}
}

// Compose has shipped majors past 2: a 5.x is newer than v2, not a stranger.
func TestDoctorAcceptsComposeBeyondV2(t *testing.T) {
	for _, v := range []string{"2.29.1", "v2.29.1", "5.5.1"} {
		var b bytes.Buffer
		lookPath, output := fakeTooling(nil, map[string]string{
			"docker --version":                        "Docker version 27.1.1\n",
			"docker compose version --short":          v + "\n",
			"docker info --format {{.ServerVersion}}": "27.1.1\n",
		})
		if err := RunDoctor(t.Context(), DoctorOptions{
			Home: doctorHome(t), LookPath: lookPath, Output: output, Out: &b,
		}); err != nil {
			t.Errorf("compose %s rejected: %v\n%s", v, err, b.String())
		}
	}
}

// A v2 that answers --short is not asked the legacy question.
func TestDoctorAcceptsComposeV2(t *testing.T) {
	var b bytes.Buffer
	lookPath, output := fakeTooling(nil, map[string]string{
		"docker --version":                        "Docker version 27.1.1\n",
		"docker compose version --short":          "2.29.1\n",
		"docker info --format {{.ServerVersion}}": "27.1.1\n",
	})
	if err := RunDoctor(t.Context(), DoctorOptions{
		Home: doctorHome(t), LookPath: lookPath, Output: output, Out: &b,
	}); err != nil {
		t.Fatalf("doctor rejected compose v2: %v\n%s", err, b.String())
	}
}

// A stopped daemon is its own failure, not a missing docker.
func TestDoctorReportsAStoppedDaemon(t *testing.T) {
	var b bytes.Buffer
	lookPath, output := fakeTooling(nil, map[string]string{
		"docker --version":                        "Docker version 27.1.1\n",
		"docker compose version --short":          "v2.29.1\n",
		"docker info --format {{.ServerVersion}}": "",
	})
	if err := RunDoctor(t.Context(), DoctorOptions{
		Home: doctorHome(t), LookPath: lookPath, Output: output, Out: &b,
	}); err == nil {
		t.Error("doctor passed with the daemon down")
	}
	if !strings.Contains(b.String(), "not reachable") {
		t.Errorf("stopped daemon not named:\n%s", b.String())
	}
}
