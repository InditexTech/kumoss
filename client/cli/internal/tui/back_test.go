// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"testing"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

func TestClassifyKey(t *testing.T) {
	cases := []struct {
		key              string
		atFirstField     bool
		selectFilterOpen bool
		wantBack         bool
	}{
		{"esc", false, false, true},
		{"esc", true, false, true},
		// huh uses esc to clear an open select filter; that must win.
		{"esc", false, true, false},
		{"ctrl+b", false, false, true},
		// ctrl+b has no filter exception: it always means back.
		{"ctrl+b", false, true, true},
		{"shift+tab", true, false, true},
		// Anywhere but the first field, huh moves back one field itself.
		{"shift+tab", false, false, false},
		{"enter", true, false, false},
		// ctrl+c is a real abort and must never read as back.
		{"ctrl+c", true, false, false},
	}
	for _, c := range cases {
		got := classifyKey(c.key, c.atFirstField, c.selectFilterOpen)
		if got != c.wantBack {
			t.Errorf("classifyKey(%q, atFirst=%v, filterOpen=%v) = %v, want %v",
				c.key, c.atFirstField, c.selectFilterOpen, got, c.wantBack)
		}
	}
}

func TestFirstVisibleFieldAllVisible(t *testing.T) {
	first := huh.NewInput().Title("first")
	groups := []*stepGroup{
		newStepGroup(first, huh.NewInput().Title("second")),
		newStepGroup(huh.NewInput().Title("third")),
	}
	if got := firstVisibleField(groups); got != huh.Field(first) {
		t.Errorf("firstVisibleField = %v, want the first group's first field", got)
	}
}

func TestFirstVisibleFieldSkipsHiddenGroups(t *testing.T) {
	wanted := huh.NewInput().Title("second group, first field")
	groups := []*stepGroup{
		newStepGroup(huh.NewInput().Title("hidden")).WithHideFunc(func() bool { return true }),
		newStepGroup(wanted, huh.NewInput().Title("also second group")),
		newStepGroup(huh.NewInput().Title("third")),
	}
	if got := firstVisibleField(groups); got != huh.Field(wanted) {
		t.Errorf("firstVisibleField = %v, want the first visible group's first field", got)
	}
}

func TestFirstVisibleFieldReevaluatesHideFunc(t *testing.T) {
	hidden := true
	firstField := huh.NewInput().Title("first")
	secondField := huh.NewInput().Title("second")
	groups := []*stepGroup{
		newStepGroup(firstField).WithHideFunc(func() bool { return hidden }),
		newStepGroup(secondField),
	}
	if got := firstVisibleField(groups); got != huh.Field(secondField) {
		t.Fatalf("while hidden: firstVisibleField = %v, want the second group's field", got)
	}
	// The hide funcs close over the wizard's state, whose answers change as the
	// user walks around, so the result must never be cached.
	hidden = false
	if got := firstVisibleField(groups); got != huh.Field(firstField) {
		t.Errorf("after unhiding: firstVisibleField = %v, want the first group's field", got)
	}
}

func TestFirstVisibleFieldAllHidden(t *testing.T) {
	groups := []*stepGroup{
		newStepGroup(huh.NewInput()).WithHideFunc(func() bool { return true }),
	}
	if got := firstVisibleField(groups); got != nil {
		t.Errorf("firstVisibleField = %v, want nil when every group is hidden", got)
	}
}

func TestWizardKeyMapBindsBackKeysOnQuit(t *testing.T) {
	km := wizardKeyMap()
	for _, k := range []tea.KeyPressMsg{
		{Code: tea.KeyEscape},
		{Code: 'b', Mod: tea.ModCtrl},
		{Code: 'c', Mod: tea.ModCtrl},
	} {
		if !key.Matches(k, km.Quit) {
			t.Errorf("key %q does not match Quit; Quit binds %v", k.String(), km.Quit.Keys())
		}
	}
}

func TestWizardKeyMapKeepsMultiSelectToggleHelp(t *testing.T) {
	km := wizardKeyMap()
	if got := km.MultiSelect.Toggle.Help().Key; got != "space" {
		t.Errorf("MultiSelect toggle help key = %q, want %q", got, "space")
	}
	bound := map[string]bool{}
	for _, k := range km.MultiSelect.Toggle.Keys() {
		bound[k] = true
	}
	for _, want := range []string{"space", "x"} {
		if !bound[want] {
			t.Errorf("MultiSelect toggle does not bind %q; binds %v", want, km.MultiSelect.Toggle.Keys())
		}
	}
}

func TestWizardKeyMapAdvertisesBackKeys(t *testing.T) {
	km := wizardKeyMap()
	const want = "shift+tab/esc/ctrl+b"
	for name, b := range map[string]key.Binding{
		"Input":       km.Input.Prev,
		"Text":        km.Text.Prev,
		"Select":      km.Select.Prev,
		"MultiSelect": km.MultiSelect.Prev,
		"Confirm":     km.Confirm.Prev,
		"Note":        km.Note.Prev,
	} {
		if got := b.Help().Key; got != want {
			t.Errorf("%s.Prev help key = %q, want %q", name, got, want)
		}
		if got := b.Help().Desc; got != "back" {
			t.Errorf("%s.Prev help desc = %q, want %q", name, got, "back")
		}
	}
}

// filteringSelect returns a Select that has been put into filter-entry mode,
// the state in which huh binds esc to "set filter".
func filteringSelect(t *testing.T) huh.Field {
	t.Helper()
	sel := huh.NewSelect[string]().
		Title("pick").
		Options(huh.NewOption("alpha", "a"), huh.NewOption("beta", "b"))
	// Through a form, so huh hands the field the keymap that makes "/" mean
	// filter. A bare field has no bindings at all.
	sf := newStepForm(newStepGroup(sel))
	sf.form.Init()
	sel.Focus()
	sel.Update(tea.KeyPressMsg{Code: '/', Text: "/"})
	return sel
}

func TestEscTakenByReadsTheFieldsLiveBindings(t *testing.T) {
	// huh copies the keymap into each field by value (field_select.go:802), so
	// the enabled flags only ever change on the field's own copy. Reading them
	// off the form's instance always says "not filtering".
	if escTakenBy(huh.NewInput().Title("name")) {
		t.Error("an input reports esc as taken; it binds no esc")
	}

	idle := huh.NewSelect[string]().Options(huh.NewOption("alpha", "a"))
	idle.Init()
	idle.Focus()
	if escTakenBy(idle) {
		t.Error("an unfiltered select reports esc as taken; its filter bindings are disabled")
	}

	if !escTakenBy(filteringSelect(t)) {
		t.Error("a select with an open filter does not report esc as taken, so esc would leave the form")
	}
}

// The form's own keymap cannot answer this question, which is why escTakenBy
// reads the field. If this ever starts failing, huh has switched to sharing
// the keymap by pointer and selectFilterOpen could be simplified.
func TestFormKeyMapCannotSeeAnOpenFilter(t *testing.T) {
	sel := huh.NewSelect[string]().Options(huh.NewOption("alpha", "a"))
	sf := newStepForm(newStepGroup(sel))
	sf.form.Init()
	sel.Focus()
	sel.Update(tea.KeyPressMsg{Code: '/', Text: "/"})

	if !escTakenBy(sel) {
		t.Fatal("the field does not report an open filter; the premise of this test is gone")
	}
	if sf.keymap.Select.SetFilter.Enabled() || sf.keymap.Select.ClearFilter.Enabled() {
		t.Error("the form's keymap now sees the open filter; escTakenBy can read it instead of the field")
	}
}

func TestEscTakenByNilField(t *testing.T) {
	if escTakenBy(nil) {
		t.Error("a nil focused field reports esc as taken")
	}
}
