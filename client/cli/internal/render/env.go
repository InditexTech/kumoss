// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// EnvPaths are the three env files the pipeline writes. Kept as a struct, not a
// slice, so the mapping file→vars stays explicit.
type EnvPaths struct {
	Core          string // src/core/.env
	IAC           string // src/services/iac/.env
	Notifications string // src/services/notifications/.env
}

// Env renders the three .env files from the answers. Generation is the only
// secret work it does: the caller reuses the existing files' values (LoadSecrets
// + Fill) and blanks the ones the user chose to rotate, so Write fills exactly
// the empty ones and writes all three 0600.
//
// The key set comes from the repo's env.sample files when Samples is set: the
// wizard fills the keys it owns, the sample supplies the rest, and keys the
// sample leaves empty are asked for and carried in Extra. With Samples nil (the
// fetch failed) it falls back to the built-in key list, which may lag the repo.
type Env struct {
	Samples *Samples
	// Extra holds the values the user supplied for sample keys with no value and
	// no wizard owner (e.g. SLACK_WEBHOOK_URL).
	Extra map[string]string
}

// Write writes the env files. s.Secrets is filled in place with any values it
// had to generate, so the caller can report them if needed. Every secret that is
// already set on s is kept as-is: the caller reuses the existing files' values
// (see LoadSecrets) and blanks only the ones the user chose to rotate, so this
// method never rotates anything on its own.
func (e *Env) Write(p EnvPaths, s *state.State) error {
	e.generate(s)

	for path, vars := range e.files(p, s) {
		if err := writeEnv(path, vars); err != nil {
			return err
		}
	}
	return nil
}

// LoadSecrets reads the secrets already present in the three env files, so the
// caller can offer to rotate them before Write. Returns false when none of the
// files exist yet (a fresh install).
func LoadSecrets(p EnvPaths) (state.Secrets, bool) {
	var s state.Secrets
	found := false
	for _, path := range []string{p.Core, p.IAC, p.Notifications} {
		vars := readEnv(path)
		if len(vars) == 0 {
			continue
		}
		found = true
		s.IACToken = first(s.IACToken, vars["KUMOSS_IAC_TOKEN"])
		s.NotificationsToken = first(s.NotificationsToken, vars["KUMOSS_NOTIFICATIONS_TOKEN"])
		s.MappingToken = first(s.MappingToken, vars["KUMOSS_MAPPING_TOKEN"])
		s.AuthzToken = first(s.AuthzToken, vars["KUMOSS_AUTHZ_TOKEN"])
		s.RustFSAccessKey = first(s.RustFSAccessKey, vars["RUSTFS_ACCESS_KEY"])
		s.RustFSSecretKey = first(s.RustFSSecretKey, vars["RUSTFS_SECRET_KEY"])
		if pw := dbPassword(vars["KUMOSS_SQL_DATABASE_URL"]); pw != "" {
			s.CoreDBPassword = first(s.CoreDBPassword, pw)
		}
	}
	return s, found
}

// Fill copies the secrets found in the env files onto s, except the keys in
// rotate, which are left empty so Write generates fresh ones. Call it with
// LoadSecrets' result before Write; a fresh install passes found=false and
// nothing is copied.
func Fill(s *state.State, existing state.Secrets, rotate []string) {
	keep := func(key, value string) string {
		for _, r := range rotate {
			if r == key {
				return ""
			}
		}
		return value
	}
	s.Secrets.IACToken = keep("KUMOSS_IAC_TOKEN", existing.IACToken)
	s.Secrets.NotificationsToken = keep("KUMOSS_NOTIFICATIONS_TOKEN", existing.NotificationsToken)
	s.Secrets.MappingToken = keep("KUMOSS_MAPPING_TOKEN", existing.MappingToken)
	s.Secrets.AuthzToken = keep("KUMOSS_AUTHZ_TOKEN", existing.AuthzToken)
	s.Secrets.RustFSAccessKey = keep("RUSTFS_ACCESS_KEY", existing.RustFSAccessKey)
	s.Secrets.RustFSSecretKey = keep("RUSTFS_SECRET_KEY", existing.RustFSSecretKey)
	s.Secrets.CoreDBPassword = keep("KUMOSS_SQL_DATABASE_URL", existing.CoreDBPassword)
}

// generate fills every secret still empty with a fresh random value. 32 bytes
// of entropy hex-encoded, matching the `openssl rand -hex 32` the samples
// recommend. Tokens must be non-empty: the generated clients reject an empty
// bearer.
//
// The Postgres password and the RustFS keys are NOT generated: docker-compose.yml
// hardcodes them (POSTGRES_PASSWORD=postgres; RustFS's built-in rustfsadmin), so
// a random value could never match the running containers. They come from the
// env sample instead.
func (e *Env) generate(s *state.State) {
	s.Secrets.IACToken = first(s.Secrets.IACToken, randomHex())
	s.Secrets.NotificationsToken = first(s.Secrets.NotificationsToken, randomHex())
	// Mapping and authz are contracts-only and disabled by default; leave them
	// empty unless the user set them, so the core does not try to use them.
}

// files maps each env file to its vars. With samples, each file carries exactly
// the sample's keys, resolved in this order: the wizard's value, then the
// sample's value, then what the user typed for an empty sample key. Without
// samples it falls back to the built-in key list.
func (e *Env) files(p EnvPaths, s *state.State) map[string]map[string]string {
	if e.Samples == nil {
		return e.fallbackFiles(p, s)
	}
	return map[string]map[string]string{
		p.Core:          resolveSample(e.Samples.Core, e.owned(s), e.Extra),
		p.IAC:           resolveSample(e.Samples.IAC, e.owned(s), e.Extra),
		p.Notifications: resolveSample(e.Samples.Notifications, e.owned(s), e.Extra),
	}
}

// resolveSample builds one env file's vars from its sample: wizard-owned value
// first, then the sample's own value, then the user's Extra value.
func resolveSample(sample *Sample, owned, extra map[string]string) map[string]string {
	vars := make(map[string]string, len(sample.Vars))
	for _, v := range sample.Vars {
		switch {
		case owned[v.Key] != "":
			vars[v.Key] = owned[v.Key]
		case v.Value != "":
			vars[v.Key] = v.Value
		default:
			vars[v.Key] = extra[v.Key]
		}
	}
	return vars
}

// owned maps every env key the wizard collects to its value. A key here wins
// over whatever the sample says; a blank value still marks the key as owned, so
// resolveSample never falls back to a sample placeholder for it.
//
// KUMOSS_SQL_DATABASE_URL and the RUSTFS keys are deliberately absent: the
// wizard does not collect them, and their sample values are the ones that match
// the containers docker-compose.yml starts.
func (e *Env) owned(s *state.State) map[string]string {
	owned := map[string]string{
		"KUMOSS_NOTIFICATIONS_TOKEN": s.Secrets.NotificationsToken,
		"KUMOSS_IAC_TOKEN":           s.Secrets.IACToken,
		"KUMOSS_MAPPING_TOKEN":       s.Secrets.MappingToken,
		"KUMOSS_AUTHZ_TOKEN":         s.Secrets.AuthzToken,
		"GIT_USER":                   s.Git.User,
		"GIT_TOKEN":                  s.Git.Token,
		"IAC_BINARY":                 s.Engine.Binary,
	}
	// Provider credentials collected by the LLM step, keyed by env-var name.
	for k, v := range s.LLM.Credentials {
		owned[k] = v
	}
	// Object-storage credentials, keyed by env-var name (STORAGE_ACCOUNT_KEY).
	// Blank entries are skipped: an empty map value must not shadow the sample's
	// default for a key the user did not actually set.
	for k, v := range s.Storage.Credentials {
		if v != "" {
			owned[k] = v
		}
	}
	for k, v := range cloudVars(s.Cloud) {
		owned[k] = v
	}
	for k, v := range s.Storage.BackendCredentials {
		owned[k] = v
	}
	return owned
}

// OwnedKeys returns the env keys the wizard collects, for Sample.NeedsAsking.
func (e *Env) OwnedKeys(s *state.State) map[string]bool {
	keys := make(map[string]bool)
	for k := range e.owned(s) {
		keys[k] = true
	}
	return keys
}

// fallbackFiles is the built-in key list, used only when the samples could not
// be fetched. It mirrors the samples at the time of writing and can lag them.
func (e *Env) fallbackFiles(p EnvPaths, s *state.State) map[string]map[string]string {
	owned := e.owned(s)
	core := map[string]string{
		"KUMOSS_NOTIFICATIONS_TOKEN": owned["KUMOSS_NOTIFICATIONS_TOKEN"],
		"KUMOSS_IAC_TOKEN":           owned["KUMOSS_IAC_TOKEN"],
		"GIT_USER":                   owned["GIT_USER"],
		"GIT_TOKEN":                  owned["GIT_TOKEN"],
		// These two match docker-compose.yml, which is what the containers
		// actually use; they are not generated.
		"RUSTFS_ACCESS_KEY":       first(s.Secrets.RustFSAccessKey, "rustfsadmin"),
		"RUSTFS_SECRET_KEY":       first(s.Secrets.RustFSSecretKey, "rustfsadmin"),
		"KUMOSS_SQL_DATABASE_URL": databaseURL(first(s.Secrets.CoreDBPassword, "postgres")),
	}
	for k, v := range s.LLM.Credentials {
		core[k] = v
	}
	// Blank storage credentials must not overwrite the defaults set above.
	for k, v := range s.Storage.Credentials {
		if v != "" {
			core[k] = v
		}
	}

	iac := map[string]string{
		"KUMOSS_IAC_TOKEN": s.Secrets.IACToken,
		"IAC_BINARY":       s.Engine.Binary,
	}
	for k, v := range cloudVars(s.Cloud) {
		iac[k] = v
	}
	for k, v := range s.Storage.BackendCredentials {
		iac[k] = v
	}

	notifications := map[string]string{
		"KUMOSS_NOTIFICATIONS_TOKEN": s.Secrets.NotificationsToken,
	}
	return map[string]map[string]string{
		p.Core:          core,
		p.IAC:           iac,
		p.Notifications: notifications,
	}
}

// cloudVars flattens the picked clouds into the iac env vars. Only the picked
// clouds are non-nil (the cloud step nils the rest).
func cloudVars(c state.Cloud) map[string]string {
	vars := map[string]string{}
	if a := c.AWS; a != nil {
		if a.Method == "profile" {
			vars["AWS_PROFILE"] = a.Profile
		} else {
			vars["AWS_ACCESS_KEY_ID"] = a.AccessKey
			vars["AWS_SECRET_ACCESS_KEY"] = a.SecretKey
		}
		vars["AWS_REGION"] = a.Region
	}
	if a := c.Azure; a != nil {
		vars["ARM_TENANT_ID"] = a.TenantID
		vars["ARM_CLIENT_ID"] = a.ClientID
		vars["ARM_CLIENT_SECRET"] = a.ClientSecret
		// ARM_SUBSCRIPTION_ID is injected per request from the scope, never set
		// here; the wizard still collects it for display, so drop it.
	}
	if a := c.GCP; a != nil {
		vars["GOOGLE_APPLICATION_CREDENTIALS"] = a.KeyFile
	}
	if a := c.OCI; a != nil {
		vars["OCI_CONFIG_FILE"] = a.ConfigPath
	}
	if a := c.Kubernetes; a != nil {
		vars["KUBE_CONFIG_PATH"] = a.KubeconfigPath
	}
	return vars
}

// databaseURL embeds the generated password in the fixed local URL. The host
// `core-db` is the compose service name.
func databaseURL(password string) string {
	return fmt.Sprintf("postgresql://postgres:%s@core-db:5432/kumoss", password)
}

// dbPassword pulls the password out of a postgres URL, or "" when it has none.
// The userinfo is everything between `//` and the last `@`; the password is
// everything after the first `:` in it, so a `:` inside the password survives.
func dbPassword(url string) string {
	at := strings.LastIndexByte(url, '@')
	slashes := strings.Index(url, "//")
	if at < 0 || slashes < 0 || at < slashes+2 {
		return ""
	}
	userinfo := url[slashes+2 : at]
	colon := strings.IndexByte(userinfo, ':')
	if colon < 0 {
		return ""
	}
	return userinfo[colon+1:]
}

// writeEnv writes KEY=value lines, one per var, sorted so runs are diffable.
// Empty values are written as `KEY=` — the compose stack reads the file as a
// whole and a missing key behaves differently from an empty one. 0600: the file
// holds secrets.
func writeEnv(path string, vars map[string]string) error {
	keys := make([]string, 0, len(vars))
	for k := range vars {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var b strings.Builder
	for _, k := range keys {
		b.WriteString(k)
		b.WriteByte('=')
		b.WriteString(vars[k])
		b.WriteByte('\n')
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(b.String()), 0o600)
}

// readEnv parses KEY=value lines, ignoring blanks and comments. A malformed line
// is skipped rather than failing: a hand-edited file should not block the run.
func readEnv(path string) map[string]string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	vars := map[string]string{}
	for line := range strings.SplitSeq(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		vars[strings.TrimSpace(k)] = strings.Trim(strings.TrimSpace(v), `"'`)
	}
	return vars
}

// first returns a if non-empty, else b.
func first(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// randomHex is 32 bytes of crypto/rand, hex-encoded.
func randomHex() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand only fails when the OS source is unavailable; there is
		// nothing sensible to do but surface it loudly.
		panic("render: cannot read randomness: " + err.Error())
	}
	return hex.EncodeToString(b)
}
