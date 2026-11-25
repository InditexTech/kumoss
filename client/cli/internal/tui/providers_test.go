// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"slices"
	"strings"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// prefixOf picks the provider row on reconfigure; wrong here means asking for
// the wrong credentials.
func TestPrefixOf(t *testing.T) {
	cases := []struct{ in, want string }{
		{"anthropic/claude-sonnet-5", "anthropic"},
		{"vertex_ai/claude-sonnet-4-5", "vertex_ai"},
		{"claude-sonnet-5", ""},
		{"/leading", ""},
		{"", ""},
	}
	for _, c := range cases {
		if got := prefixOf(c.in); got != c.want {
			t.Errorf("prefixOf(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// The index that preselects a row must resolve back to it; unknown means Other.
func TestProviderIndexAndAt(t *testing.T) {
	for i, p := range llmProviders {
		// Two rows share the openai prefix, so the first match wins by design.
		if first := providerIndex(p.Prefix); first > i || (first == i && providerAt(i).Name != p.Name) {
			t.Errorf("providerIndex(%q) = %d, want %d", p.Prefix, first, i)
		}
		if got := providerAt(i); got.Name != p.Name {
			t.Errorf("providerAt(%d) = %q, want %q", i, got.Name, p.Name)
		}
	}

	if got := providerIndex("not-a-provider"); got != -1 {
		t.Errorf("unknown prefix index = %d, want -1", got)
	}
	for _, idx := range []int{-1, -2, len(llmProviders)} {
		if got := providerAt(idx); !got.Freeform {
			t.Errorf("providerAt(%d) = %q, want the Other row", idx, got.Name)
		}
	}
}

// The seeds match config.yaml, so a fresh install and a hand-edited file do not
// disagree on the model the user sees.
func TestAnthropicAndVertexSeedTheShippedModels(t *testing.T) {
	for _, c := range []struct{ name, model, small string }{
		{"Anthropic", "anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-5-5"},
		{"Google Vertex AI", "vertex_ai/claude-sonnet-5-5", "vertex_ai/gemini-3.8-flash"},
	} {
		p := providerAt(providerIndex(prefixOf(c.model)))
		if p.Name != c.name || p.DefaultModel != c.model || p.DefaultSmallModel != c.small {
			t.Errorf("%s seeds %s / %s, want %s / %s", p.Name, p.DefaultModel, p.DefaultSmallModel, c.model, c.small)
		}
	}
}

// Every row needs a prefix and a default model, or the form seeds an empty id.
func TestLLMProvidersAreComplete(t *testing.T) {
	seen := map[string]string{}
	for _, p := range llmProviders {
		if p.Prefix == "" || p.DefaultModel == "" || p.DefaultSmallModel == "" {
			t.Errorf("%q has an empty prefix or model: %+v", p.Name, p)
		}
		// Only openai may duplicate: two rows, and the first must win.
		if prev, dup := seen[p.Prefix]; dup && p.Prefix != "openai" {
			t.Errorf("duplicate prefix %q: %q and %q", p.Prefix, prev, p.Name)
		}
		seen[p.Prefix] = p.Name
	}
}

// The two openai rows are indistinguishable on reconfigure, which is only safe
// while they write the same variables: a divergence would silently drop one.
func TestSharedOpenAIPrefixRowsAreInterchangeable(t *testing.T) {
	var names [][]string
	for _, p := range llmProviders {
		if p.Prefix != "openai" {
			continue
		}
		keys := make([]string, len(p.Credentials))
		for i, c := range p.Credentials {
			keys[i] = c.Name
		}
		names = append(names, keys)
	}
	if len(names) != 2 {
		t.Fatalf("openai rows = %d, want 2", len(names))
	}
	if !slices.Equal(names[0], names[1]) {
		t.Errorf("openai rows write different variables: %v vs %v", names[0], names[1])
	}
}

// secretByName is what a credential's name says about it. An identifier is
// not a secret even when it is called a key: AWS_ACCESS_KEY_ID names the
// account making the request, the way a username does, and masking it only
// stops the user checking what they typed. AWS_SECRET_ACCESS_KEY beside it is
// the one that has to be hidden.
func secretByName(name string) bool {
	if strings.HasSuffix(name, "_ID") {
		return false
	}
	return strings.Contains(name, "_KEY") ||
		strings.Contains(name, "SECRET") ||
		strings.Contains(name, "_TOKEN") ||
		strings.Contains(name, "CREDENTIALS")
}

// Only a credential is masked. A project id, a region or an API base must stay
// readable while it is typed, so anything not named like a secret is visible.
func TestOnlyCredentialsAreMasked(t *testing.T) {
	all := func() []credential {
		var out []credential
		for _, p := range llmProviders {
			out = append(out, p.Credentials...)
		}
		for _, m := range storageModels {
			out = append(out, m.Credentials...)
		}
		return out
	}
	for _, c := range all() {
		if want := secretByName(c.Name); c.Secret != want {
			t.Errorf("%s: Secret = %v, want %v", c.Name, c.Secret, want)
		}
	}
}

// The rule the table is checked against, checked itself: a miswritten
// heuristic would pass every row by agreeing with whatever is there.
func TestSecretByName(t *testing.T) {
	for name, want := range map[string]bool{
		"AWS_ACCESS_KEY_ID":     false,
		"AWS_SECRET_ACCESS_KEY": true,
		"AWS_REGION_NAME":       false,
		"ANTHROPIC_API_KEY":     true,
		"HOSTED_VLLM_API_KEY":   true,
		"HOSTED_VLLM_API_BASE":  false,
		"VERTEXAI_PROJECT":      false,
		"VERTEXAI_CREDENTIALS":  true,
		"STORAGE_ACCOUNT_KEY":   true,
		"KUMOSS_IAC_TOKEN":      true,
	} {
		if got := secretByName(name); got != want {
			t.Errorf("secretByName(%q) = %v, want %v", name, got, want)
		}
	}
}

// The Select offers every provider plus exactly one Other row at the end.
func TestLLMProviderOptions(t *testing.T) {
	opts := llmProviderOptions()
	if len(opts) != len(llmProviders)+1 {
		t.Fatalf("options = %d, want %d", len(opts), len(llmProviders)+1)
	}
	if opts[len(opts)-1].Value != -1 {
		t.Errorf("last option value = %d, want -1 (Other)", opts[len(opts)-1].Value)
	}
}

func TestStorageModelByName(t *testing.T) {
	for _, m := range storageModels {
		got := storageModelByName(m.Model)
		if got == nil || got.Model != m.Model {
			t.Errorf("storageModelByName(%q) = %+v", m.Model, got)
		}
	}
	if storageModelByName("nope") != nil {
		t.Error("unknown model returned a row")
	}

	// The bundled store is managed and needs no credentials typed in.
	if m := storageModelByName("bundled"); !m.Managed || len(m.Credentials) != 0 {
		t.Errorf("bundled = %+v", m)
	}
	// Repository-declared state is unmanaged: the bucket must stay empty.
	if m := storageModelByName("repository"); m.Managed {
		t.Error("repository state marked managed")
	}
}

func TestSelected(t *testing.T) {
	picked := []string{"aws", "gcp"}
	if !selected(picked, "aws") || !selected(picked, "gcp") {
		t.Error("picked cloud not found")
	}
	if selected(picked, "azure") {
		t.Error("unpicked cloud reported as selected")
	}
	if selected(nil, "aws") {
		t.Error("nil slice reported a match")
	}
}

// cloudPicked mirrors ensureCloud: every key it allocates must be detectable.
func TestCloudPickedAndEnsureCloud(t *testing.T) {
	s := &state.State{}
	for _, c := range clouds {
		if cloudPicked(s, c.Key) {
			t.Errorf("%q picked on a fresh state", c.Key)
		}
		if ensureCloud(s, c.Key) == nil {
			t.Fatalf("ensureCloud(%q) = nil", c.Key)
		}
		if !cloudPicked(s, c.Key) {
			t.Errorf("%q not picked after ensureCloud", c.Key)
		}
	}

	if ensureCloud(s, "unknown") != nil {
		t.Error("ensureCloud accepted an unknown key")
	}
	if cloudPicked(s, "unknown") {
		t.Error("cloudPicked reported an unknown key as picked")
	}
}

// ensureCloud must not reset an existing struct, or a reconfigure drops it.
func TestEnsureCloudKeepsExistingValues(t *testing.T) {
	s := &state.State{Cloud: state.Cloud{AWS: &state.AWSAuth{Method: "profile", Profile: "corp"}}}
	got, ok := ensureCloud(s, "aws").(*state.AWSAuth)
	if !ok {
		t.Fatal("ensureCloud(aws) is not *AWSAuth")
	}
	if got.Profile != "corp" || got.Method != "profile" {
		t.Errorf("existing AWS auth was reset: %+v", got)
	}

	// A fresh AWS struct starts in static mode so the key fields are shown.
	s = &state.State{}
	if got := ensureCloud(s, "aws").(*state.AWSAuth); got.Method != "static" {
		t.Errorf("new AWS method = %q, want static", got.Method)
	}
}

// The storage model has to be selectable: nothing else sets the discriminator,
// and it is not saved in kumoss.yaml, so without this select pickStorage always
// returned the first row and external storage was unreachable.
func TestStorageModelOptionsCoverEveryModel(t *testing.T) {
	opts := storageModelOptions()
	if len(opts) != len(storageModels) {
		t.Fatalf("options = %d, want %d", len(opts), len(storageModels))
	}
	for i, m := range storageModels {
		if got := opts[i].Value; got != m.Model {
			t.Errorf("option %d = %q, want %q", i, got, m.Model)
		}
		if got := pickStorage(&state.State{Storage: state.Storage{Model: m.Model}}); got.Model != m.Model {
			t.Errorf("pickStorage(%q) = %q", m.Model, got.Model)
		}
	}
}
