// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// typeInto types text into a form's first field. huh writes through to the
// bound local on every key, which is how these tests give the production code
// an answer without a terminal.
func typeInto(sf *stepForm, text string) {
	field := sf.groups[0].fields[0]
	field.Focus()
	for _, r := range text {
		field.Update(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
}

// scriptedWizard runs each form through the matching action, in order.
func scriptedWizard(actions ...func(*stepForm) error) (*Wizard, *int) {
	runs := 0
	w := &Wizard{}
	w.runForm = func(sf *stepForm) error {
		defer func() { runs++ }()
		if runs < len(actions) {
			return actions[runs](sf)
		}
		return nil
	}
	return w, &runs
}

func answer(text string) func(*stepForm) error {
	return func(sf *stepForm) error {
		typeInto(sf, text)
		return nil
	}
}

func goBack(*stepForm) error { return errBack }

func freeformState() *state.State {
	return &state.State{LLM: state.LLM{Credentials: map[string]string{}}}
}

// Typing has to reach the bound local, or every test below would pass for the
// wrong reason.
func TestTypeIntoReachesTheBoundValue(t *testing.T) {
	w, _ := scriptedWizard(answer("MY_KEY"), goBack)
	s := freeformState()

	if err := w.collectFreeformCredentials(s); err != nil && !errors.Is(err, errBack) {
		t.Fatalf("collectFreeformCredentials returned %v", err)
	}
	// A name was typed, so the loop moved on to ask for its value.
	if len(s.LLM.Credentials) != 0 {
		t.Fatalf("credentials = %v, want none committed yet", s.LLM.Credentials)
	}
}

func TestFreeformBackFromFirstNameReturnsErrBack(t *testing.T) {
	w, runs := scriptedWizard(goBack)
	s := freeformState()

	err := w.collectFreeformCredentials(s)

	if !errors.Is(err, errBack) {
		t.Fatalf("collectFreeformCredentials returned %v, want errBack", err)
	}
	if *runs != 1 {
		t.Errorf("ran %d forms, want 1", *runs)
	}
	if len(s.LLM.Credentials) != 0 {
		t.Errorf("credentials = %v, want none", s.LLM.Credentials)
	}
}

func TestFreeformBackFromValueReopensName(t *testing.T) {
	w, runs := scriptedWizard(
		answer("MY_KEY"), // name
		goBack,           // value: step back to the name
		answer(""),       // name again, left blank to finish
	)
	s := freeformState()

	if err := w.collectFreeformCredentials(s); err != nil {
		t.Fatalf("collectFreeformCredentials returned %v, want nil", err)
	}
	// Name, value, name again.
	if *runs != 3 {
		t.Errorf("ran %d forms, want 3", *runs)
	}
	if len(s.LLM.Credentials) != 0 {
		t.Errorf("credentials = %v, want the abandoned pair not committed", s.LLM.Credentials)
	}
}

func TestFreeformBackAfterOnePairStaysInLoop(t *testing.T) {
	w, _ := scriptedWizard(
		answer("MY_KEY"), // name
		answer("s3cret"), // value, committing the pair
		goBack,           // second name: back out of the loop
	)
	s := freeformState()

	if err := w.collectFreeformCredentials(s); err != nil {
		t.Fatalf("collectFreeformCredentials returned %v, want nil", err)
	}
	// A pair was already given, so backing out finishes the loop forward
	// rather than discarding the section.
	if got := s.LLM.Credentials["MY_KEY"]; got != "s3cret" {
		t.Errorf("credentials[MY_KEY] = %q, want %q", got, "s3cret")
	}
}

func TestFreeformBlankNameFinishes(t *testing.T) {
	w, runs := scriptedWizard(answer(""))
	s := freeformState()

	if err := w.collectFreeformCredentials(s); err != nil {
		t.Fatalf("collectFreeformCredentials returned %v, want nil", err)
	}
	if *runs != 1 {
		t.Errorf("ran %d forms, want 1", *runs)
	}
}
