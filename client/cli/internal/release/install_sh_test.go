// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package release

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
)

// installScript is the real file, so a change to it is covered here.
const installScript = "../../../../install.sh"

// fakeRelease serves the two endpoints install.sh asks for: the latest
// redirect, and the download directory.
func fakeRelease(t *testing.T, version, archiveName string, archive []byte) *httptest.Server {
	t.Helper()
	sum := sha256.Sum256(archive)
	checksums := fmt.Sprintf("%s  %s\n", hex.EncodeToString(sum[:]), archiveName)

	mux := http.NewServeMux()
	// install.sh reads the tag off where this lands; curl -I makes it a HEAD.
	mux.HandleFunc("/latest", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/tag/v"+version, http.StatusFound)
	})
	mux.HandleFunc("/tag/v"+version, func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("release page"))
	})
	mux.HandleFunc("/download/v"+version+"/"+archiveName, func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write(archive)
	})
	mux.HandleFunc("/download/v"+version+"/checksums.txt", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(checksums))
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

// tarGz builds a one-file archive holding the binary install.sh extracts.
func tarGz(t *testing.T, name string, body []byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	tw := tar.NewWriter(zw)
	hdr := &tar.Header{Name: name, Mode: 0o755, Size: int64(len(body)), Typeflag: tar.TypeReg}
	if err := tw.WriteHeader(hdr); err != nil {
		t.Fatalf("tar header: %v", err)
	}
	if _, err := tw.Write(body); err != nil {
		t.Fatalf("tar body: %v", err)
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("tar close: %v", err)
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("gzip close: %v", err)
	}
	return buf.Bytes()
}

// requireTools skips rather than reporting a failure about the host.
func requireTools(t *testing.T) {
	t.Helper()
	if runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		t.Skipf("install.sh supports linux and darwin, not %s", runtime.GOOS)
	}
	for _, tool := range []string{"bash", "tar", "uname"} {
		if _, err := exec.LookPath(tool); err != nil {
			t.Skipf("%s is not installed", tool)
		}
	}
	if !anyTool("curl", "wget") {
		t.Skip("neither curl nor wget is installed")
	}
	if !anyTool("sha256sum", "shasum") {
		t.Skip("neither sha256sum nor shasum is installed")
	}
	if _, err := os.Stat(installScript); err != nil {
		t.Skipf("install.sh not found at %s: %v", installScript, err)
	}
}

func anyTool(names ...string) bool {
	for _, n := range names {
		if _, err := exec.LookPath(n); err == nil {
			return true
		}
	}
	return false
}

// archiveName is built the way the script builds it.
func archiveName(version string) string {
	return fmt.Sprintf("kumoss_%s_%s_%s.tar.gz", version, runtime.GOOS, runtime.GOARCH)
}

// runInstaller runs install.sh against the fake host.
func runInstaller(t *testing.T, srv *httptest.Server, installDir string, extraEnv ...string) (string, error) {
	t.Helper()
	script, err := filepath.Abs(installScript)
	if err != nil {
		t.Fatalf("abs: %v", err)
	}
	cmd := exec.Command("bash", script)
	cmd.Env = append(os.Environ(),
		"KUMOSS_RELEASE_BASE="+srv.URL,
		"KUMOSS_INSTALL_DIR="+installDir,
		"KUMOSS_VERSION=",
	)
	cmd.Env = append(cmd.Env, extraEnv...)
	out, err := cmd.CombinedOutput()
	return string(out), err
}

// The default path takes the version from the redirect. Using the empty
// KUMOSS_VERSION asked for kumoss__<os>_<arch>.tar.gz, which 404s.
func TestInstallScriptInstallsTheLatestRelease(t *testing.T) {
	requireTools(t)
	const version = "1.2.3"
	name := archiveName(version)
	srv := fakeRelease(t, version, name, tarGz(t, "kumoss", []byte("#!/bin/sh\necho installed\n")))

	dir := t.TempDir()
	out, err := runInstaller(t, srv, dir)
	if err != nil {
		t.Fatalf("install.sh failed: %v\n%s", err, out)
	}

	body, err := os.ReadFile(filepath.Join(dir, "kumoss"))
	if err != nil {
		t.Fatalf("binary not installed: %v\n%s", err, out)
	}
	if !bytes.Contains(body, []byte("echo installed")) {
		t.Errorf("installed binary = %q, not the archive's content", body)
	}
	// An empty version means the script never learnt which release it got.
	if want := "Installed kumoss " + version; !bytes.Contains([]byte(out), []byte(want)) {
		t.Errorf("output does not report %q:\n%s", want, out)
	}
}

// An explicit KUMOSS_VERSION skips the redirect and installs that release,
// with or without the leading v.
func TestInstallScriptHonoursAnExplicitVersion(t *testing.T) {
	requireTools(t)
	const version = "9.9.9"
	name := archiveName(version)
	srv := fakeRelease(t, version, name, tarGz(t, "kumoss", []byte("pinned")))

	for _, requested := range []string{version, "v" + version} {
		dir := t.TempDir()
		out, err := runInstaller(t, srv, dir, "KUMOSS_VERSION="+requested)
		if err != nil {
			t.Fatalf("KUMOSS_VERSION=%s: %v\n%s", requested, err, out)
		}
		body, err := os.ReadFile(filepath.Join(dir, "kumoss"))
		if err != nil {
			t.Fatalf("KUMOSS_VERSION=%s: binary not installed: %v\n%s", requested, err, out)
		}
		if string(body) != "pinned" {
			t.Errorf("KUMOSS_VERSION=%s: installed %q", requested, body)
		}
	}
}

// shimPath symlinks every tool on PATH into one directory, minus the hidden
// ones — the only honest way to test a host without them.
func shimPath(t *testing.T, hide ...string) string {
	t.Helper()
	shim := t.TempDir()
	hidden := make(map[string]bool, len(hide))
	for _, h := range hide {
		hidden[h] = true
	}
	for _, dir := range filepath.SplitList(os.Getenv("PATH")) {
		if dir == "" {
			continue
		}
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue // an unreadable or missing PATH entry is not this test's problem
		}
		for _, e := range entries {
			name := e.Name()
			if hidden[name] {
				continue
			}
			link := filepath.Join(shim, name)
			if _, err := os.Lstat(link); err == nil {
				continue // the first PATH entry wins, as the shell does it
			}
			_ = os.Symlink(filepath.Join(dir, name), link)
		}
	}
	if _, err := os.Stat(filepath.Join(shim, "tar")); err != nil {
		t.Skip("could not build a shim PATH holding tar")
	}
	return shim
}

// With neither installed the script must stop and ask for one, and must not
// reach for a substitute — a kumoss binary on PATH is no reason to continue.
func TestInstallScriptRequiresCurlOrWget(t *testing.T) {
	requireTools(t)
	const version = "1.2.3"
	name := archiveName(version)
	srv := fakeRelease(t, version, name, tarGz(t, "kumoss", []byte("should not be installed")))

	// A plausible stand-in downloader on PATH, to prove it is not used.
	binDir := t.TempDir()
	stub := filepath.Join(binDir, "kumoss")
	if err := os.WriteFile(stub, []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("write stub: %v", err)
	}
	shim := shimPath(t, "curl", "wget")

	dir := t.TempDir()
	out, err := runInstaller(t, srv, dir, "PATH="+binDir+string(os.PathListSeparator)+shim)
	if err == nil {
		t.Fatalf("install.sh exited 0 with neither curl nor wget:\n%s", out)
	}
	if _, statErr := os.Stat(filepath.Join(dir, "kumoss")); statErr == nil {
		t.Errorf("a binary was installed without curl or wget:\n%s", out)
	}
	// The message has to tell the user what to do, not just what is missing.
	for _, want := range []string{"curl", "wget", "install"} {
		if !bytes.Contains([]byte(out), []byte(want)) {
			t.Errorf("error does not mention %q:\n%s", want, out)
		}
	}
}

// The check runs before anything is downloaded, so the host is told at once.
func TestInstallScriptChecksForADownloaderUpFront(t *testing.T) {
	requireTools(t)
	const version = "1.2.3"
	srv := fakeRelease(t, version, archiveName(version), tarGz(t, "kumoss", []byte("x")))
	shim := shimPath(t, "curl", "wget")

	dir := t.TempDir()
	out, _ := runInstaller(t, srv, dir, "PATH="+shim, "KUMOSS_VERSION="+version)
	if bytes.Contains([]byte(out), []byte("Downloading")) {
		t.Errorf("the script started downloading before checking for a downloader:\n%s", out)
	}
}

// The checksum is all that stands between a mirror and arbitrary code on PATH.
func TestInstallScriptAbortsOnAChecksumMismatch(t *testing.T) {
	requireTools(t)
	const version = "1.2.3"
	name := archiveName(version)
	// checksums.txt describes one archive; the host serves another.
	advertised := tarGz(t, "kumoss", []byte("expected"))
	served := tarGz(t, "kumoss", []byte("malicious"))
	sum := sha256.Sum256(advertised)

	mux := http.NewServeMux()
	mux.HandleFunc("/latest", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/tag/v"+version, http.StatusFound)
	})
	mux.HandleFunc("/download/v"+version+"/"+name, func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write(served)
	})
	mux.HandleFunc("/download/v"+version+"/checksums.txt", func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprintf(w, "%s  %s\n", hex.EncodeToString(sum[:]), name)
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	dir := t.TempDir()
	out, err := runInstaller(t, srv, dir)
	if err == nil {
		t.Fatalf("install.sh exited 0 on a checksum mismatch:\n%s", out)
	}
	if _, statErr := os.Stat(filepath.Join(dir, "kumoss")); statErr == nil {
		t.Errorf("a binary was installed despite the mismatch:\n%s", out)
	}
}
