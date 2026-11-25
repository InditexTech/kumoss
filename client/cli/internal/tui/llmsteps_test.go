// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
	"reflect"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

func TestLLMStepsHasSevenSlots(t *testing.T) {
	w, _ := stubWizard()
	if got := len(w.llmSteps()); got != 7 {
		t.Errorf("llmSteps = %d slots, want 7", got)
	}
}

// ranSlot reports whether the slot opened a form, by counting runs around it.
func ranSlot(t *testing.T, providers []string, slot int) bool {
	t.Helper()
	w, runs := stubWizard()
	// Copied: the role step reorders the slice in place, so sharing the
	// caller's would let one assertion corrupt the next.
	own := append([]string(nil), providers...)
	s := &state.State{LLM: state.LLM{Providers: own, Credentials: map[string]string{}}}
	before := *runs
	if err := w.llmSteps()[slot](s); err != nil && !errors.Is(err, errSkip) {
		t.Fatalf("slot %d returned %v", slot, err)
	}
	return *runs > before
}

func TestLLMSlotSkipPredicates(t *testing.T) {
	// Slots are 0-indexed here: 1 = role, 4 = provider 0 freeform,
	// 5 = provider 1, 6 = provider 1 freeform.
	cases := []struct {
		name      string
		providers []string
		role      bool
		freeform0 bool
		provider1 bool
		freeform1 bool
	}{
		{"one named provider", []string{"anthropic"}, false, false, false, false},
		{"two named providers", []string{"anthropic", "openai"}, true, false, true, false},
		{"Other alone", []string{""}, false, true, false, false},
		{"named then Other", []string{"anthropic", ""}, true, false, true, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := ranSlot(t, c.providers, 1); got != c.role {
				t.Errorf("role slot ran = %v, want %v", got, c.role)
			}
			if got := ranSlot(t, c.providers, 4); got != c.freeform0 {
				t.Errorf("provider 0 freeform slot ran = %v, want %v", got, c.freeform0)
			}
			if got := ranSlot(t, c.providers, 5); got != c.provider1 {
				t.Errorf("provider 1 slot ran = %v, want %v", got, c.provider1)
			}
			if got := ranSlot(t, c.providers, 6); got != c.freeform1 {
				t.Errorf("provider 1 freeform slot ran = %v, want %v", got, c.freeform1)
			}
		})
	}
}

func TestLLMProviderStepPreselectsOther(t *testing.T) {
	// "Other" has an empty prefix and the select represents it as -1. Dropping
	// it from the preselection would mean walking back to the provider list and
	// forward again silently loses the Other pick.
	if got := llmPreselect([]string{""}); !reflect.DeepEqual(got, []int{-1}) {
		t.Errorf("llmPreselect([\"\"]) = %v, want [-1]", got)
	}
	if got := llmPreselect([]string{"anthropic", ""}); !reflect.DeepEqual(got, []int{providerIndex("anthropic"), -1}) {
		t.Errorf("llmPreselect = %v, want the named row and the Other row", got)
	}
}

func TestLLMRoleOrderRoundTrip(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{
		// What slot 1 writes: option-list order, not role order.
		Providers: []string{"anthropic", "openai"},
		Model:     "openai/gpt-5",
	}}

	if err := w.llmRoleStep(s); err != nil {
		t.Fatalf("llmRoleStep returned %v", err)
	}

	// s.LLM.Providers is in role order, index 0 serving the complex model.
	if want := []string{"openai", "anthropic"}; !reflect.DeepEqual(s.LLM.Providers, want) {
		t.Errorf("Providers = %v, want %v", s.LLM.Providers, want)
	}
}

func TestLLMRoleOrderUnknownModelDefaultsToFirst(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{
		Providers: []string{"anthropic", "openai"},
		Model:     "mistral/x", // matches neither pick
	}}

	if err := w.llmRoleStep(s); err != nil {
		t.Fatalf("llmRoleStep returned %v", err)
	}

	if want := []string{"anthropic", "openai"}; !reflect.DeepEqual(s.LLM.Providers, want) {
		t.Errorf("Providers = %v, want the list order a fresh run gets", s.LLM.Providers)
	}
}

func TestLLMRoleStepSkipsForOneProvider(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{Providers: []string{"anthropic"}}}
	if err := w.llmRoleStep(s); !errors.Is(err, errSkip) {
		t.Errorf("llmRoleStep with one provider returned %v, want errSkip", err)
	}
}

func TestLLMTwoProvidersReducedToOne(t *testing.T) {
	w, _ := stubWizard()
	// The user went back and dropped the second provider.
	s := &state.State{LLM: state.LLM{
		Providers:   []string{"anthropic"},
		Credentials: map[string]string{},
	}}
	steps := w.llmSteps()

	if err := steps[5](s); !errors.Is(err, errSkip) {
		t.Errorf("provider 1 slot returned %v, want errSkip", err)
	}
	if err := steps[6](s); !errors.Is(err, errSkip) {
		t.Errorf("provider 1 freeform slot returned %v, want errSkip", err)
	}

	// The survivor fills both roles, so it is asked for the cheap model too.
	if err := steps[3](s); err != nil {
		t.Fatalf("provider 0 slot returned %v", err)
	}
	if s.LLM.Model == "" {
		t.Error("the surviving provider was not asked for the complex model")
	}
	if s.LLM.SmallModel == "" {
		t.Error("the surviving provider was not asked for the cheap model")
	}
}

// rowNamed is the select index of a provider row.
func rowNamed(t *testing.T, name string) int {
	t.Helper()
	for i, p := range llmProviders {
		if p.Name == name {
			return i
		}
	}
	t.Fatalf("no provider row named %q", name)
	return -1
}

// Two rows share the prefix "openai", so a prefix cannot name which row the
// user picked. Resolving one back through providerIndex collapses the
// OpenAI-compatible row into the OpenAI row.
func TestLLMSlotKeepsTheExactPickedRow(t *testing.T) {
	compatible := rowNamed(t, "OpenAI-compatible (LM Studio, LocalAI…)")
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{Credentials: map[string]string{}}}

	// What picking only "OpenAI-compatible" leaves behind.
	w.llmPicked = []int{compatible}
	s.LLM.Providers = prefixesOf(w.llmPicked)

	if err := w.llmSteps()[3](s); err != nil {
		t.Fatalf("provider slot 0 returned %v", err)
	}

	if want := llmProviders[compatible].DefaultModel; s.LLM.Model != want {
		t.Errorf("Model = %q, want %q — the slot resolved to the wrong row", s.LLM.Model, want)
	}
}

// Both OpenAI rows at once is a legal pick, and the two slots must stay apart.
func TestLLMSlotsKeepTwoRowsSharingAPrefix(t *testing.T) {
	plain := rowNamed(t, "OpenAI")
	compatible := rowNamed(t, "OpenAI-compatible (LM Studio, LocalAI…)")
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{Credentials: map[string]string{}}}
	w.llmPicked = []int{plain, compatible}
	s.LLM.Providers = prefixesOf(w.llmPicked)

	if err := w.llmSteps()[3](s); err != nil {
		t.Fatalf("provider slot 0 returned %v", err)
	}
	if err := w.llmSteps()[5](s); err != nil {
		t.Fatalf("provider slot 1 returned %v", err)
	}

	if want := llmProviders[plain].DefaultModel; s.LLM.Model != want {
		t.Errorf("Model = %q, want %q", s.LLM.Model, want)
	}
	if want := llmProviders[compatible].DefaultSmallModel; s.LLM.SmallModel != want {
		t.Errorf("SmallModel = %q, want %q", s.LLM.SmallModel, want)
	}
}

// Dropping a provider must not leave its model behind as the survivor's
// answer: the stack would boot unable to call a model whose key nobody asked
// for, and preflight would not notice.
func TestLLMDroppedProvidersModelIsNotReused(t *testing.T) {
	anthropic := rowNamed(t, "Anthropic")
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{
		Providers:   []string{"anthropic"},
		Model:       "anthropic/claude-sonnet-5-5",
		SmallModel:  "openai/gpt-5-mini", // left by the provider just removed
		Credentials: map[string]string{},
	}}
	w.llmPicked = []int{anthropic}

	if err := w.llmSteps()[3](s); err != nil {
		t.Fatalf("provider slot 0 returned %v", err)
	}

	if prefixOf(s.LLM.SmallModel) != "anthropic" {
		t.Errorf("SmallModel = %q, want a model served by the surviving provider", s.LLM.SmallModel)
	}
	if s.LLM.Model != "anthropic/claude-sonnet-5-5" {
		t.Errorf("Model = %q, want the stored model kept, it still matches", s.LLM.Model)
	}
}

// A model in config.yaml belonging to another vendor must not be offered
// either; it reaches the form by the same route.
func TestLLMSeededModelFromAnotherProviderIsNotReused(t *testing.T) {
	anthropic := rowNamed(t, "Anthropic")
	w, _ := stubWizard()
	w.Doc = map[string]any{"llm": map[string]any{"model": "openai/gpt-5"}}
	s := &state.State{LLM: state.LLM{Providers: []string{"anthropic"}, Credentials: map[string]string{}}}
	w.llmPicked = []int{anthropic}

	if err := w.llmSteps()[3](s); err != nil {
		t.Fatalf("provider slot 0 returned %v", err)
	}
	if prefixOf(s.LLM.Model) != "anthropic" {
		t.Errorf("Model = %q, want a model served by the picked provider", s.LLM.Model)
	}
}

// With no stored model, an empty prefix must not match the Other row's empty
// prefix and quietly promote it to the complex role — especially now that the
// role step commits on a back the user never confirmed.
func TestLLMRoleStepDoesNotPromoteOtherByDefault(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{LLM: state.LLM{Providers: []string{"anthropic", ""}}}
	w.llmPicked = []int{rowNamed(t, "Anthropic"), -1}

	if err := w.llmRoleStep(s); err != nil {
		t.Fatalf("llmRoleStep returned %v", err)
	}

	if s.LLM.Providers[0] != "anthropic" {
		t.Errorf("Providers = %v, want the named provider left in the complex role", s.LLM.Providers)
	}
}
