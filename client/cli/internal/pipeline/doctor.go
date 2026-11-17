// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// DoctorOptions is the resolved input to RunDoctor.
type DoctorOptions struct {
	// Home is the root every check reads from, resolved from --home. Doctor
	// never writes under it.
	Home home.Home
	// Source says how Home was chosen, so a missing home can name the flag
	// the user needs: --home for anything but the default.
	Source home.Source
	// LookPath and Output are the seams tests stub, so the checks run without
	// docker. nil runs the real binary.
	LookPath func(string) (string, error)
	Output   func(ctx context.Context, name string, args ...string) (string, error)
	Out      io.Writer
}

// Check is one line of the doctor report.
type Check struct {
	Label  string // what was checked, e.g. "docker compose"
	OK     bool   // false marks the line FAIL
	Detail string // the version, the path, or why it failed
}

// RunDoctor checks what the stack needs from the machine, then the generated
// files. Every check is printed, so one failure never hides the rest; the
// returned error counts the failed ones and drives the exit status. A home that
// never ran init is a pass, not a failure: it only points at kumoss init.
func RunDoctor(ctx context.Context, opts DoctorOptions) error {
	out := opts.Out
	if out == nil {
		out = io.Discard
	}
	lookPath := opts.LookPath
	if lookPath == nil {
		lookPath = exec.LookPath
	}
	output := opts.Output
	if output == nil {
		output = runOutput
	}

	fmt.Fprintf(out, "Kumoss %s (stack %s)\n\n", buildinfo.Version, buildinfo.KumossTag())

	checks := []Check{
		checkBinary("docker", lookPath, output),
		checkCompose(ctx, lookPath, output),
		checkDaemon(ctx, output),
		checkHome(opts.Home),
	}
	for _, c := range checks {
		printCheck(out, c)
	}

	// The files are checked only once a home exists: an install that never ran
	// init is the expected state of a fresh machine, not a failure. Doctor still
	// reports the machine checks above, which is what a fresh machine needs.
	exists, err := state.StateFileExist(opts.Home.StateFile())
	if err != nil {
		return err
	}
	if !exists {
		fmt.Fprintf(out, "\nNo %s yet. %s\n", opts.Home.StateFile(), initHint(opts.Home, opts.Source))
		return failed(checks)
	}

	s, err := state.Load(opts.Home.StateFile())
	if err != nil {
		return err
	}
	problems := Preflight(opts.Home, s)
	if len(problems) == 0 {
		printCheck(out, Check{Label: "generated files", OK: true, Detail: "agree with kumoss.yaml"})
		return failed(checks)
	}
	for _, p := range problems {
		printCheck(out, Check{Label: "generated files", Detail: p.Message + " (" + p.Fix + ")"})
	}
	checks = append(checks, Check{Label: "generated files"})
	return failed(checks)
}

// initHint is the command that creates the missing home. Only the default root
// needs no flag: every other source was chosen explicitly, and init would
// otherwise write ~/.kumoss instead of the home doctor just checked.
func initHint(h home.Home, src home.Source) string {
	if src == home.SourceDefault {
		return "Run kumoss init."
	}
	return "Run kumoss init --home " + h.Root + " to install into this home."
}

// failed returns an error naming how many required checks failed, so the exit
// status matches the report.
func failed(checks []Check) error {
	n := 0
	for _, c := range checks {
		if !c.OK {
			n++
		}
	}
	if n == 0 {
		return nil
	}
	return fmt.Errorf("%s failed", plural(n, "check", "checks"))
}

// printCheck writes one aligned line: ok or FAIL, the label, then the detail.
func printCheck(w io.Writer, c Check) {
	mark := "ok  "
	if !c.OK {
		mark = "FAIL"
	}
	fmt.Fprintf(w, "%-4s %-16s %s\n", mark, c.Label, c.Detail)
}

// checkBinary reports whether name is on PATH, with its version when the binary
// answers. Only a failed lookup counts as missing: a binary that cannot print a
// version is still installed.
func checkBinary(name string, lookPath func(string) (string, error), output func(context.Context, string, ...string) (string, error)) Check {
	path, err := lookPath(name)
	if err != nil {
		return Check{Label: name, Detail: "not found on PATH"}
	}
	version, err := output(context.Background(), name, "--version")
	if err != nil {
		return Check{Label: name, OK: true, Detail: path}
	}
	return Check{Label: name, OK: true, Detail: path + " (" + firstLine(version) + ")"}
}

// checkCompose needs compose v2 or newer: the v1 binary has neither
// `--policy missing` nor the health reporting the status table reads. Compose
// has shipped major versions beyond 2, so the check is a lower bound, not a
// match.
func checkCompose(ctx context.Context, lookPath func(string) (string, error), output func(context.Context, string, ...string) (string, error)) Check {
	if _, err := lookPath("docker"); err != nil {
		return Check{Label: "docker compose", Detail: "needs docker"}
	}
	version, err := output(ctx, "docker", "compose", "version", "--short")
	if err != nil {
		// `version --short` is v2-only, so a failure can mean either a missing
		// plugin or a v1 binary that does not know the flag.
		if _, legacyErr := output(ctx, "docker", "compose", "version"); legacyErr == nil {
			return Check{Label: "docker compose", Detail: "v1 found; v2 or newer is required"}
		}
		return Check{Label: "docker compose", Detail: "not installed; install Docker Compose v2 or newer"}
	}
	v := strings.TrimSpace(version)
	if major, ok := composeMajor(v); !ok || major < 2 {
		return Check{Label: "docker compose", Detail: v + " found; v2 or newer is required"}
	}
	return Check{Label: "docker compose", OK: true, Detail: v}
}

// composeMajor reads the leading integer of a compose version, tolerating the
// v prefix and any suffix.
func composeMajor(v string) (int, bool) {
	v = strings.TrimPrefix(v, "v")
	end := 0
	for end < len(v) && v[end] >= '0' && v[end] <= '9' {
		end++
	}
	if end == 0 {
		return 0, false
	}
	n, err := strconv.Atoi(v[:end])
	return n, err == nil
}

// checkDaemon reports whether the engine answers. The CLI, not the version, is
// what tells an installed-but-stopped Docker apart from a missing one.
func checkDaemon(ctx context.Context, output func(context.Context, string, ...string) (string, error)) Check {
	out, err := output(ctx, "docker", "info", "--format", "{{.ServerVersion}}")
	if err != nil {
		return Check{Label: "docker daemon", Detail: "not reachable; start Docker"}
	}
	return Check{Label: "docker daemon", OK: true, Detail: "server " + strings.TrimSpace(out)}
}

// checkHome needs the root writable: init writes every generated file under it.
// It writes nothing, not even a probe file: doctor reports, so a typo'd --home
// must not leave an empty directory behind. Permission bits are the closest a
// read-only check gets; the kernel still has the final say (ACLs, read-only
// mounts), which only init discovers.
func checkHome(h home.Home) Check {
	dir := h.Root
	var info os.FileInfo
	for {
		var err error
		info, err = os.Stat(dir)
		if err == nil {
			if !info.IsDir() {
				return Check{Label: "home", Detail: dir + " is not a directory"}
			}
			break
		}
		if !os.IsNotExist(err) {
			return Check{Label: "home", Detail: dir + ": " + err.Error()}
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return Check{Label: "home", Detail: dir + " has no existing parent"}
		}
		dir = parent
	}
	if info.Mode().Perm()&0o200 == 0 {
		return Check{Label: "home", Detail: dir + " is not writable"}
	}
	if dir != h.Root {
		return Check{Label: "home", OK: true, Detail: h.Root + " does not exist yet; init will create it"}
	}
	return Check{Label: "home", OK: true, Detail: h.Root}
}

// firstLine keeps a version string on the check's one line.
func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '\n'); i > 0 {
		return s[:i]
	}
	return s
}

// runOutput runs one command and returns its combined output.
func runOutput(ctx context.Context, name string, args ...string) (string, error) {
	out, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
	return string(out), err
}
