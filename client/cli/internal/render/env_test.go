// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

func envPathsIn(t *testing.T) EnvPaths {
	t.Helper()
	dir := t.TempDir()
	return EnvPaths{
		Core:          filepath.Join(dir, "core", ".env"),
		IAC:           filepath.Join(dir, "iac", ".env"),
		Notifications: filepath.Join(dir, "notif", ".env"),
	}
}

// A fresh install gets a token per service, and the files hold them.
func TestWriteGeneratesTokensAndWritesEveryFile(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{}
	e := &Env{Samples: &Samples{
		Core:          ParseSample("KUMOSS_IAC_TOKEN=\n"),
		IAC:           ParseSample("KUMOSS_IAC_TOKEN=\n"),
		Notifications: ParseSample("KUMOSS_NOTIFICATIONS_TOKEN=\n"),
	}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}

	if s.Secrets.IACToken == "" || s.Secrets.NotificationsToken == "" {
		t.Fatal("tokens not generated onto the state")
	}
	// The same token must reach core and iac, or the core's bearer is rejected.
	core := readEnv(p.Core)
	iac := readEnv(p.IAC)
	if core["KUMOSS_IAC_TOKEN"] != s.Secrets.IACToken || iac["KUMOSS_IAC_TOKEN"] != s.Secrets.IACToken {
		t.Errorf("iac token differs between files: core=%q iac=%q", core["KUMOSS_IAC_TOKEN"], iac["KUMOSS_IAC_TOKEN"])
	}
	if readEnv(p.Notifications)["KUMOSS_NOTIFICATIONS_TOKEN"] != s.Secrets.NotificationsToken {
		t.Error("notifications token not written")
	}
}

// The files hold secrets, so they must not be world-readable.
func TestWriteUsesOwnerOnlyPermissions(t *testing.T) {
	p := envPathsIn(t)
	if err := (&Env{Samples: &Samples{Core: ParseSample("A=1\n"), IAC: ParseSample("B=2\n"), Notifications: ParseSample("C=3\n")}}).Write(p, &state.State{}); err != nil {
		t.Fatalf("Write: %v", err)
	}
	for _, path := range []string{p.Core, p.IAC, p.Notifications} {
		info, err := os.Stat(path)
		if err != nil {
			t.Fatalf("stat %s: %v", path, err)
		}
		if perm := info.Mode().Perm(); perm != 0o600 {
			t.Errorf("%s mode = %o, want 600", path, perm)
		}
	}
}

// An existing token is kept, not regenerated: rotating it would break a running
// stack whose clients hold the old value.
func TestWriteKeepsExistingTokens(t *testing.T) {
	p := envPathsIn(t)
	s := &state.State{Secrets: state.Secrets{IACToken: "keep-me", NotificationsToken: "keep-me-too"}}
	e := &Env{Samples: &Samples{Core: ParseSample("KUMOSS_IAC_TOKEN=\n"), IAC: ParseSample("KUMOSS_IAC_TOKEN=\n"), Notifications: ParseSample("KUMOSS_NOTIFICATIONS_TOKEN=\n")}}
	if err := e.Write(p, s); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := readEnv(p.Core)["KUMOSS_IAC_TOKEN"]; got != "keep-me" {
		t.Errorf("token rotated: %q", got)
	}
}

// LoadSecrets reads what the files hold, so the caller can offer rotation.
func TestLoadSecretsReadsTheFiles(t *testing.T) {
	p := envPathsIn(t)
	if err := writeEnv(p.Core, map[string]string{
		"KUMOSS_IAC_TOKEN":        "core-token",
		"KUMOSS_SQL_DATABASE_URL": "postgresql://postgres:s3cret@core-db:5432/kumoss",
	}); err != nil {
		t.Fatalf("writeEnv: %v", err)
	}
	got, found := LoadSecrets(p)
	if !found {
		t.Fatal("found = false, want true when a file exists")
	}
	if got.IACToken != "core-token" {
		t.Errorf("IACToken = %q", got.IACToken)
	}
	if got.CoreDBPassword != "s3cret" {
		t.Errorf("CoreDBPassword = %q", got.CoreDBPassword)
	}
}

// A fresh install has no files, and that is not an error.
func TestLoadSecretsReportsNothingWhenNoFiles(t *testing.T) {
	if _, found := LoadSecrets(envPathsIn(t)); found {
		t.Error("found = true for a fresh install")
	}
}

// Fill copies the existing values across and leaves the rotated keys empty, so
// Write generates fresh ones for exactly those.
func TestFillRespectsRotation(t *testing.T) {
	s := &state.State{}
	existing := state.Secrets{IACToken: "old-iac", NotificationsToken: "old-notif"}
	Fill(s, existing, []string{"KUMOSS_IAC_TOKEN"})

	if s.Secrets.IACToken != "" {
		t.Errorf("rotated token kept: %q", s.Secrets.IACToken)
	}
	if s.Secrets.NotificationsToken != "old-notif" {
		t.Errorf("unrotated token lost: %q", s.Secrets.NotificationsToken)
	}
}

// Without samples the built-in list still produces a usable file set, with the
// values docker-compose.yml expects.
func TestFallbackFilesMatchTheComposeDefaults(t *testing.T) {
	p := envPathsIn(t)
	if err := (&Env{}).Write(p, &state.State{}); err != nil {
		t.Fatalf("Write: %v", err)
	}
	core := readEnv(p.Core)
	if core["RUSTFS_ACCESS_KEY"] != "rustfsadmin" || core["RUSTFS_SECRET_KEY"] != "rustfsadmin" {
		t.Errorf("rustfs keys = %q/%q, want the compose defaults", core["RUSTFS_ACCESS_KEY"], core["RUSTFS_SECRET_KEY"])
	}
	if want := "postgresql://postgres:postgres@core-db:5432/kumoss"; core["KUMOSS_SQL_DATABASE_URL"] != want {
		t.Errorf("database url = %q, want %q", core["KUMOSS_SQL_DATABASE_URL"], want)
	}
}

// dbPassword must survive a colon inside the password and a @ in the userinfo.
func TestDBPassword(t *testing.T) {
	cases := []struct{ url, want string }{
		{"postgresql://postgres:s3cret@core-db:5432/kumoss", "s3cret"},
		{"postgresql://postgres:a:b:c@core-db:5432/kumoss", "a:b:c"},
		{"postgresql://postgres@core-db:5432/kumoss", ""},
		{"not a url", ""},
		{"", ""},
	}
	for _, c := range cases {
		if got := dbPassword(c.url); got != c.want {
			t.Errorf("dbPassword(%q) = %q, want %q", c.url, got, c.want)
		}
	}
}

// writeEnv sorts its keys so two runs diff cleanly, and writes an empty value as
// KEY= rather than dropping the key: compose distinguishes missing from empty.
func TestWriteEnvSortsAndKeepsEmptyKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), "x.env")
	if err := writeEnv(path, map[string]string{"B": "2", "A": "", "C": "3"}); err != nil {
		t.Fatalf("writeEnv: %v", err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if got, want := string(raw), "A=\nB=2\nC=3\n"; got != want {
		t.Errorf("content = %q, want %q", got, want)
	}
}

// readEnv skips comments, blanks and malformed lines, and strips quotes: a
// hand-edited file must not block the run.
func TestReadEnvToleratesHandEdits(t *testing.T) {
	path := filepath.Join(t.TempDir(), "x.env")
	body := "# comment\n\nA=1\nB=\"two\"\nno equals sign\nC='three'\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	got := readEnv(path)
	if got["A"] != "1" || got["B"] != "two" || got["C"] != "three" {
		t.Errorf("parsed = %v", got)
	}
	if _, ok := got["no equals sign"]; ok {
		t.Error("malformed line was parsed")
	}
}

// cloudVars writes only the picked clouds; the cloud step nils the rest.
func TestCloudVarsOnlyWritesPickedClouds(t *testing.T) {
	got := cloudVars(state.Cloud{
		AWS:   &state.AWSAuth{Method: "static", AccessKey: "ak", SecretKey: "sk", Region: "eu-west-1"},
		Azure: &state.AzureAuth{TenantID: "t", ClientID: "c", ClientSecret: "s"},
	})
	if got["AWS_ACCESS_KEY_ID"] != "ak" || got["AWS_REGION"] != "eu-west-1" {
		t.Errorf("aws vars = %v", got)
	}
	if got["ARM_TENANT_ID"] != "t" {
		t.Errorf("azure vars = %v", got)
	}
	// ARM_SUBSCRIPTION_ID is supplied per request by the frontend, never here.
	if _, ok := got["ARM_SUBSCRIPTION_ID"]; ok {
		t.Error("ARM_SUBSCRIPTION_ID written to the env file")
	}
	if _, ok := got["GOOGLE_APPLICATION_CREDENTIALS"]; ok {
		t.Error("unpicked GCP wrote a var")
	}
}

// The AWS named-profile method writes AWS_PROFILE instead of static keys.
func TestCloudVarsAWSProfile(t *testing.T) {
	got := cloudVars(state.Cloud{AWS: &state.AWSAuth{Method: "profile", Profile: "corp"}})
	if got["AWS_PROFILE"] != "corp" {
		t.Errorf("AWS_PROFILE = %q", got["AWS_PROFILE"])
	}
	if _, ok := got["AWS_ACCESS_KEY_ID"]; ok {
		t.Error("profile method also wrote static keys")
	}
}

// randomHex must be long enough and different each call, or every install would
// share a token.
func TestRandomHexIsUniqueAndLong(t *testing.T) {
	a, b := randomHex(), randomHex()
	if a == b {
		t.Fatal("two calls returned the same value")
	}
	if len(a) != 64 || strings.Trim(a, "0123456789abcdef") != "" {
		t.Errorf("randomHex = %q, want 64 hex chars", a)
	}
}
