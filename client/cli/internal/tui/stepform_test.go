// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

func twoFieldForm() (*stepForm, huh.Field, huh.Field) {
	first := huh.NewInput().Title("first")
	second := huh.NewInput().Title("second")
	return newStepForm(newStepGroup(first, second)), first, second
}

func TestFilterPassesThroughUnrelatedKeys(t *testing.T) {
	f, _, _ := twoFieldForm()
	for _, k := range []tea.KeyPressMsg{
		{Code: tea.KeyEnter},
		{Code: 'a'},
		{Code: tea.KeyDown},
	} {
		got, back := f.filterKey(k, true, false)
		if back {
			t.Errorf("key %q read as back, want pass-through", k.String())
		}
		if got != tea.Msg(k) {
			t.Errorf("key %q was rewritten to %v, want the identical message", k.String(), got)
		}
	}
}

func TestFilterConvertsShiftTabAtFirstField(t *testing.T) {
	f, _, _ := twoFieldForm()
	shiftTab := tea.KeyPressMsg{Code: tea.KeyTab, Mod: tea.ModShift}
	if shiftTab.String() != keyPrevField {
		t.Fatalf("synthetic shift+tab stringifies as %q, want %q", shiftTab.String(), keyPrevField)
	}

	// At the top of the form there is no earlier field, so the press becomes a
	// key that Quit binds and the form exits backwards.
	got, back := f.filterKey(shiftTab, true, false)
	if !back {
		t.Error("shift+tab at the first field did not read as back")
	}
	k, ok := got.(tea.KeyPressMsg)
	if !ok || k.String() != keyBackAnywhere {
		t.Errorf("shift+tab was forwarded as %v, want a %q press that matches Quit", got, keyBackAnywhere)
	}

	// Anywhere else huh moves back a field itself.
	got, back = f.filterKey(shiftTab, false, false)
	if back {
		t.Error("shift+tab away from the first field read as back")
	}
	if got != tea.Msg(shiftTab) {
		t.Errorf("shift+tab was rewritten to %v, want the identical message", got)
	}
}

func TestFilterLeavesEscToHuhWhileFilterOpen(t *testing.T) {
	f, _, _ := twoFieldForm()
	esc := tea.KeyPressMsg{Code: tea.KeyEscape}
	got, back := f.filterKey(esc, false, true)
	if back {
		t.Error("esc read as back while a select filter was open")
	}
	if got != tea.Msg(esc) {
		t.Errorf("esc was rewritten to %v, want the identical message", got)
	}
}

func TestBackFlagIsPerRun(t *testing.T) {
	f, _, _ := twoFieldForm()

	// First run: esc means back, so huh's abort reads as errBack.
	f.resetBack()
	if _, back := f.filterKey(tea.KeyPressMsg{Code: tea.KeyEscape}, false, false); back {
		f.back = true
	}
	if got := f.outcome(huh.ErrUserAborted); !errors.Is(got, errBack) {
		t.Fatalf("after esc, outcome = %v, want errBack", got)
	}

	// Second run of the same form: ctrl+c is a real abort. If the flag leaked
	// across runs this would be mistaken for another back request.
	f.resetBack()
	if _, back := f.filterKey(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl}, false, false); back {
		f.back = true
	}
	got := f.outcome(huh.ErrUserAborted)
	if errors.Is(got, errBack) {
		t.Fatal("ctrl+c after a back request read as errBack, want the abort")
	}
	if !errors.Is(got, huh.ErrUserAborted) {
		t.Errorf("outcome = %v, want huh.ErrUserAborted", got)
	}
}

func TestOutcomePassesOtherResultsThrough(t *testing.T) {
	f, _, _ := twoFieldForm()
	f.resetBack()
	if got := f.outcome(nil); got != nil {
		t.Errorf("outcome(nil) = %v, want nil", got)
	}
	boom := errors.New("boom")
	if got := f.outcome(boom); !errors.Is(got, boom) {
		t.Errorf("outcome(boom) = %v, want boom", got)
	}
}

func TestAtFirstFieldTracksFocus(t *testing.T) {
	f, _, second := twoFieldForm()
	if !f.atFirstField() {
		t.Fatal("a freshly built form does not report the cursor on its first field")
	}
	f.form.Init()
	f.form.Update(huh.NextField())
	if f.form.GetFocusedField() != second {
		t.Skip("huh did not advance the focus outside a running program")
	}
	if f.atFirstField() {
		t.Error("atFirstField stayed true after the focus moved to the second field")
	}
}
