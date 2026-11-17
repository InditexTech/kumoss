// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"fmt"
	"os"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// Problem is one reason `kumoss run` refuses to start the stack.
type Problem struct {
	// Message says what is wrong, naming the file or variable.
	Message string
	// Fix is the command that resolves it.
	Fix string
}

// Preflight reports what stands between the recorded answers and a stack that
// can start.
func Preflight(h home.Home, s *state.State) []Problem {
	// A home missing its files has nothing worth reconciling, and reading the
	// ones that survived would bury the real problem under cascading noise.
	if missing := missingFiles(h, s); len(missing) > 0 {
		return missing
	}
	return append(configDrift(h, s), envProblems(h, s)...)
}

// envProblems reconciles the env files: drift for the answers kumoss.yaml
// records, presence for the credentials it deliberately does not.
func envProblems(h home.Home, s *state.State) []Problem {
	core := render.ReadEnv(h.CoreEnv())
	iac := render.ReadEnv(h.ServiceEnv("iac"))

	problems := cloudDrift(iac, s)
	// The provider in llm.model decides which variables the core needs; the
	// optional ones document a blank as a supported setup.
	for _, key := range tui.RequiredEnvKeys(s) {
		if core[key] == "" {
			problems = append(problems, Problem{
				Message: key + " is blank in core/.env, and " + s.LLM.Provider + " needs it",
				Fix:     "kumoss config llm",
			})
		}
	}
	for _, key := range cloudSecrets(s.Cloud) {
		if iac[key] == "" {
			problems = append(problems, Problem{
				Message: key + " is blank in services/iac/.env",
				Fix:     "kumoss config cloud",
			})
		}
	}
	problems = append(problems, tokenProblem(core, iac, "KUMOSS_IAC_TOKEN", "services/iac/.env")...)

	if s.Notifications.Enabled {
		notifications := render.ReadEnv(h.ServiceEnv("notifications"))
		problems = append(problems, tokenProblem(core, notifications,
			"KUMOSS_NOTIFICATIONS_TOKEN", "services/notifications/.env")...)
		if notifications["SLACK_WEBHOOK_URL"] == "" {
			problems = append(problems, Problem{
				Message: "SLACK_WEBHOOK_URL is blank in services/notifications/.env, and the service refuses to start without it",
				Fix:     "kumoss config notifications",
			})
		}
	}
	return problems
}

// cloudDrift compares the recorded cloud answers against services/iac/.env.
//
// Only non-empty values are compared, which is exactly the non-secret set:
// the credentials are yaml:"-", so they come back blank from a load. That is
// also why the differing values are safe to print.
func cloudDrift(iac map[string]string, s *state.State) []Problem {
	want := render.CloudVars(s.Cloud)
	keys := make([]string, 0, len(want))
	for key := range want {
		keys = append(keys, key)
	}
	// Sorted, or a map walk would reorder the report between runs.
	sort.Strings(keys)

	var problems []Problem
	for _, key := range keys {
		if want[key] == "" || iac[key] == want[key] {
			continue
		}
		problems = append(problems, Problem{
			Message: fmt.Sprintf("%s is %q in services/iac/.env; kumoss.yaml records %q", key, iac[key], want[key]),
			Fix:     "kumoss config cloud",
		})
	}
	return problems
}

// cloudSecrets are the credential variables kumoss.yaml never stores, so only
// their presence can be checked. A named AWS profile and GCP Application
// Default Credentials authenticate without any of them.
func cloudSecrets(c state.Cloud) []string {
	var keys []string
	if a := c.AWS; a != nil && a.Method != "profile" {
		keys = append(keys, "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
	}
	if c.Azure != nil {
		keys = append(keys, "ARM_CLIENT_SECRET")
	}
	if a := c.GCP; a != nil && a.Method == "json" {
		keys = append(keys, "GOOGLE_CREDENTIALS")
	}
	return keys
}

// tokenProblem checks one bearer token pair. The value is never printed: the
// key alone says which one to rotate.
func tokenProblem(core, side map[string]string, key, sideFile string) []Problem {
	switch {
	case core[key] == "" || side[key] == "":
		return []Problem{{
			Message: key + " is blank in core/.env or " + sideFile + ", and the core refuses to boot without it",
			Fix:     "kumoss config secrets",
		}}
	case core[key] != side[key]:
		return []Problem{{
			Message: key + " differs between core/.env and " + sideFile + ", so the sidecar rejects every call",
			Fix:     "kumoss config secrets",
		}}
	}
	return nil
}

// ownedConfigKey is one config.yaml value the wizard writes, paired with what
// kumoss.yaml says it should be and the section that rewrites it.
type ownedConfigKey struct {
	path    []string
	want    any
	section string
}

// ownedConfigKeys mirrors render.overlay: the keys the wizard owns, and only
// those. Everything else in config.yaml is the user's to tune.
//
// A recorded string of "" is skipped rather than compared: those fields are
// omitempty, so an absent key and a deliberate blank are indistinguishable
// after a load, and guessing wrong would block a working stack.
func ownedConfigKeys(s *state.State) []ownedConfigKey {
	keys := []ownedConfigKey{
		{[]string{"services", "notifications", "enabled"}, s.Notifications.Enabled, "notifications"},
	}
	add := func(section string, value string, path ...string) {
		if value != "" {
			keys = append(keys, ownedConfigKey{path, value, section})
		}
	}
	add("llm", s.LLM.Model, "llm", "model")
	add("llm", s.LLM.SmallModel, "llm", "small_model")
	add("git", s.Git.Provider, "git", "provider")
	add("git", s.Git.AuthorName, "git", "author_name")
	add("git", s.Git.AuthorEmail, "git", "author_email")
	add("state", s.Storage.Provider, "storage", "provider")
	add("state", s.Storage.Bucket, "storage", "bucket")
	add("state", s.Storage.TerraformStateBucket, "storage", "terraform_state_bucket")
	add("state", s.Storage.Region, "storage", "region")
	add("state", s.Storage.EndpointURL, "storage", "endpoint_url")
	add("state", s.Storage.PublicEndpointURL, "storage", "public_endpoint_url")

	// The tuning knobs are pointers: nil means the forms never asked, so the
	// repo's own value stands and there is nothing to reconcile.
	if v := s.LLM.Temperature; v != nil {
		keys = append(keys, ownedConfigKey{[]string{"llm", "temperature"}, *v, "llm"})
	}
	if v := s.LLM.MaxOutputTokens; v != nil {
		keys = append(keys, ownedConfigKey{[]string{"llm", "max_output_tokens"}, *v, "llm"})
	}
	if v := s.LLM.Timeout; v != nil {
		keys = append(keys, ownedConfigKey{[]string{"llm", "timeout"}, *v, "llm"})
	}
	return keys
}

// configDrift compares the owned keys against the config.yaml on disk. The
// file carries no secrets, so a differing value is safe to print.
func configDrift(h home.Home, s *state.State) []Problem {
	raw, err := os.ReadFile(h.ConfigYAML())
	if err != nil {
		return nil
	}
	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return []Problem{{
			Message: h.ConfigYAML() + " is not valid YAML: " + err.Error(),
			Fix:     "kumoss init",
		}}
	}
	var problems []Problem
	for _, k := range ownedConfigKeys(s) {
		got, ok := lookup(doc, k.path...)
		if ok && fmt.Sprint(got) == fmt.Sprint(k.want) {
			continue
		}
		problems = append(problems, Problem{
			Message: fmt.Sprintf("%s is %s in config.yaml; kumoss.yaml records %v",
				strings.Join(k.path, "."), shown(got, ok), k.want),
			Fix: "kumoss config " + k.section,
		})
	}
	return problems
}

// lookup walks a decoded YAML document to a nested scalar.
func lookup(doc map[string]any, path ...string) (any, bool) {
	var cur any = doc
	for _, part := range path {
		m, ok := cur.(map[string]any)
		if !ok {
			return nil, false
		}
		if cur, ok = m[part]; !ok {
			return nil, false
		}
	}
	return cur, true
}

// shown renders the on-disk value, distinguishing an absent key from a blank.
func shown(v any, ok bool) string {
	if !ok {
		return "absent"
	}
	return fmt.Sprintf("%v", v)
}

// requiredFiles are the files the stack cannot start without. The
// notifications env exists only when that service is on, so demanding it from
// a stack that turned it off would block a valid install.
func requiredFiles(h home.Home, s *state.State) []string {
	files := []string{
		h.ComposeFile(),
		h.ComposeOverride(),
		h.ConfigYAML(),
		h.CoreEnv(),
		h.ServiceEnv("iac"),
	}
	if s.Notifications.Enabled {
		files = append(files, h.ServiceEnv("notifications"))
	}
	return files
}

// missingFiles points at init, not config: a section edit rewrites a file, it
// does not recreate a home that was never installed.
func missingFiles(h home.Home, s *state.State) []Problem {
	var problems []Problem
	for _, path := range requiredFiles(h, s) {
		if _, err := os.Stat(path); err != nil {
			problems = append(problems, Problem{
				Message: "missing " + path,
				Fix:     "kumoss init",
			})
		}
	}
	return problems
}
