// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"slices"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// prefixOf derives the provider row from a stored model id. Getting this wrong
// preselects the wrong provider on reconfigure, which then asks for the wrong
// credentials.
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

// providerIndex and providerAt must agree: the index that preselects a row must
// resolve back to that same row, and an unknown prefix lands on Other.
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

// Every row must carry a prefix and a non-empty default model, or the seeded
// form would submit an empty model id.
func TestLLMProvidersAreComplete(t *testing.T) {
	seen := map[string]string{}
	for _, p := range llmProviders {
		if p.Prefix == "" || p.DefaultModel == "" || p.DefaultSmallModel == "" {
			t.Errorf("%q has an empty prefix or model: %+v", p.Name, p)
		}
		// Two rows may share a prefix (openai hosts both OpenAI and
		// OpenAI-compatible), but the first must win a lookup, so duplicates
		// are only tolerated for openai.
		if prev, dup := seen[p.Prefix]; dup && p.Prefix != "openai" {
			t.Errorf("duplicate prefix %q: %q and %q", p.Prefix, prev, p.Name)
		}
		seen[p.Prefix] = p.Name
	}
}

// The two openai rows share a prefix, so providerIndex cannot tell them apart
// on reconfigure. That is only safe while they write the same credential
// variables: if one gains a key the other lacks, a re-run would silently drop
// it from the .env file.
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

// ensureCloud must return the existing struct rather than resetting it, or
// reconfigure would silently drop stored credentials.
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
