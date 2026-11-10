// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// EnvPaths are the three env files the pipeline writes. A struct, not a slice,
// so the file→vars mapping stays explicit.
type EnvPaths struct {
	Core          string // src/core/.env
	IAC           string // src/services/iac/.env
	Notifications string // src/services/notifications/.env
}

// Env renders the three .env files from the answers. The key set comes from the
// repo's env.sample files; with Samples nil (the fetch failed) it falls back to
// the built-in key list, which may lag the repo.
type Env struct {
	Samples *Samples
	// Extra holds what the user typed for sample keys with no value and no
	// wizard owner (e.g. SLACK_WEBHOOK_URL).
	Extra map[string]string
}

// Write writes the env files, generating onto s only the secrets still empty.
// It never rotates: the caller clears what the user chose to regenerate.
func (e *Env) Write(p EnvPaths, s *state.State) error {
	// Files generates onto s, so call it once and write what it returned.
	files := e.Files(p, s)
	for path, vars := range files {
		if err := writeEnv(path, vars); err != nil {
			return err
		}
	}
	return nil
}

// Files returns what Write would produce, keyed by path, without touching the
// disk. It generates the same tokens onto s, so a dry run shows real content.
func (e *Env) Files(p EnvPaths, s *state.State) map[string]map[string]string {
	e.generate(s)
	return e.files(p, s)
}

// RenderEnvFile returns the bytes writeEnv would write.
func RenderEnvFile(vars map[string]string) []byte {
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
	return []byte(b.String())
}

// LoadSecrets reads the secrets already in the env files, so the caller can
// offer to rotate them. False when no file exists yet (a fresh install).
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

// Fill copies LoadSecrets' result onto s, leaving the keys in rotate empty so
// Write generates fresh ones.
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

// generate fills every empty token with 32 random bytes, hex-encoded. The
// Postgres password and RustFS keys are not generated: docker-compose.yml
// hardcodes them, so a random value could never match the containers.
func (e *Env) generate(s *state.State) {
	s.Secrets.IACToken = first(s.Secrets.IACToken, randomHex())
	s.Secrets.NotificationsToken = first(s.Secrets.NotificationsToken, randomHex())
	// Mapping and authz stay empty: contracts-only, disabled by default.
}

// files maps each env file to its vars, from the samples when they were
// fetched and from the built-in key list otherwise.
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

// ownedKey reports whether the wizard owns the key, blank value included.
func ownedKey(owned map[string]string, key string) bool {
	_, ok := owned[key]
	return ok
}

// resolveSample resolves one env file: wizard value, then the sample's, then
// the user's Extra. Every sample key appears even when all three are empty.
//
// Collected credentials are appended even when the sample omits them: LLM and
// cloud vars are provider-specific and appear there only as commented examples,
// so iterating the sample alone dropped every one (VERTEXAI_*, ANTHROPIC_*…).
func resolveSample(sample *Sample, owned, extra map[string]string) map[string]string {
	vars := make(map[string]string, len(sample.Vars))
	seen := make(map[string]bool, len(sample.Vars))
	for _, v := range sample.Vars {
		seen[v.Key] = true
		switch {
		case owned[v.Key] != "" || ownedKey(owned, v.Key):
			vars[v.Key] = owned[v.Key]
		case v.Value != "":
			vars[v.Key] = v.Value
		default:
			vars[v.Key] = extra[v.Key]
		}
	}
	for k, v := range owned {
		if !seen[k] && v != "" {
			vars[k] = v
		}
	}
	return vars
}

// owned maps every env key the wizard collects to its value, which wins over
// the sample. Credentials drop their blank entries so an empty value cannot
// shadow a sample default; secrets and cloud vars keep theirs, since an empty
// var is how the stack says "not configured".
//
// KUMOSS_SQL_DATABASE_URL and the RUSTFS keys are absent on purpose: only the
// sample's values match the containers docker-compose.yml starts.
func (e *Env) owned(s *state.State) map[string]string {
	// Every key is set even when blank, or the sample's dev-*-token placeholder
	// would win for a secret the wizard deliberately left empty.
	owned := map[string]string{
		"KUMOSS_NOTIFICATIONS_TOKEN": s.Secrets.NotificationsToken,
		"KUMOSS_IAC_TOKEN":           s.Secrets.IACToken,
		"KUMOSS_MAPPING_TOKEN":       s.Secrets.MappingToken,
		"KUMOSS_AUTHZ_TOKEN":         s.Secrets.AuthzToken,
		"GIT_USER":                   s.Git.User,
		"GIT_TOKEN":                  s.Git.Token,
		"IAC_BINARY":                 s.Engine.Binary,
		"SLACK_WEBHOOK_URL":          s.Notifications.SlackWebhookURL,
	}
	// LLM credentials, keyed by env-var name. Blanks skipped, as below.
	for k, v := range s.LLM.Credentials {
		if v != "" {
			owned[k] = v
		}
	}
	// Object-storage credentials (STORAGE_ACCOUNT_KEY). Blanks skipped so they
	// cannot shadow a sample default the user never overrode.
	for k, v := range s.Storage.Credentials {
		if v != "" {
			owned[k] = v
		}
	}
	for k, v := range cloudVars(s.Cloud) {
		owned[k] = v
	}
	for k, v := range s.Storage.BackendCredentials {
		if v != "" {
			owned[k] = v
		}
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

// fallbackFiles is the built-in key list, used only when the sample fetch
// failed. It mirrors the samples at the time of writing and can lag them.
func (e *Env) fallbackFiles(p EnvPaths, s *state.State) map[string]map[string]string {
	owned := e.owned(s)
	core := map[string]string{
		"KUMOSS_NOTIFICATIONS_TOKEN": owned["KUMOSS_NOTIFICATIONS_TOKEN"],
		"KUMOSS_IAC_TOKEN":           owned["KUMOSS_IAC_TOKEN"],
		"GIT_USER":                   owned["GIT_USER"],
		"GIT_TOKEN":                  owned["GIT_TOKEN"],
		// Not generated: only these match the containers compose starts.
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
	// Carried here too, or a failed sample fetch writes the notifications file
	// without its one required var.
	if v := s.Notifications.SlackWebhookURL; v != "" {
		notifications["SLACK_WEBHOOK_URL"] = v
	}
	return map[string]map[string]string{
		p.Core:          core,
		p.IAC:           iac,
		p.Notifications: notifications,
	}
}

// cloudVars flattens the picked clouds into the iac env vars; the cloud step
// nils the rest.
func cloudVars(c state.Cloud) map[string]string {
	vars := map[string]string{}
	if a := c.AWS; a != nil {
		if a.Method == "profile" {
			// AWS_PROFILE alone would read the image's own empty ~/.aws,
			// which the mount never reaches.
			vars["AWS_SHARED_CREDENTIALS_FILE"] = ContainerAWSProfile + "/credentials"
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
		// ARM_SUBSCRIPTION_ID is absent: the frontend supplies it per request.
	}
	if a := c.GCP; a != nil {
		// Inline JSON wins: it needs no mount, so it cannot break on a file
		// the container cannot see.
		if a.InlineJSON != "" {
			vars["GOOGLE_CREDENTIALS"] = a.InlineJSON
		} else {
			// Empty, never containerPath(""): no key means fall back to
			// Application Default Credentials.
			vars["GOOGLE_APPLICATION_CREDENTIALS"] = ""
			if a.KeyFile != "" {
				vars["GOOGLE_APPLICATION_CREDENTIALS"] = containerPath(cloudGCP, a.KeyFile)
			}
		}
	}
	if a := c.OCI; a != nil {
		vars["OCI_CONFIG_FILE"] = containerPath(cloudOCI, a.ConfigPath)
	}
	if a := c.Kubernetes; a != nil {
		vars["KUBE_CONFIG_PATH"] = containerPath(cloudKube, a.KubeconfigPath)
	}
	return vars
}

// databaseURL embeds the password in the local URL; core-db is the service name.
func databaseURL(password string) string {
	return fmt.Sprintf("postgresql://postgres:%s@core-db:5432/kumoss", password)
}

// dbPassword pulls the password out of a postgres URL, or "" when it has none.
// Split on the LAST @ and the FIRST :, so a : inside the password survives.
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

// writeEnv writes KEY=value lines, sorted so runs are diffable. An empty value
// is written as `KEY=`: the stack reads that differently from a missing key.
// Via writeFile, so a half-finished write cannot truncate the only copy of the
// stack's bearer tokens.
func writeEnv(path string, vars map[string]string) error {
	return writeFile(path, RenderEnvFile(vars), 0o600)
}

// readEnv parses KEY=value lines. A malformed line is skipped, not fatal: a
// hand-edited file should not block the run.
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
		// Only fails if the OS source is gone; nothing sensible to do but shout.
		panic("render: cannot read randomness: " + err.Error())
	}
	return hex.EncodeToString(b)
}
