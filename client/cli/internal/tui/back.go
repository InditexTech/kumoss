// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

// The keys that leave a form backwards. shift+tab is not bound on Quit: huh
// matches Quit before the focused group sees the key, so binding it there
// would kill moving back one field. The filter converts it instead, and only
// when there is no earlier field to move to.
const (
	keyBackAnywhere  = "esc"
	keyBackAlternate = "ctrl+b"
	keyPrevField     = "shift+tab"
	keyAbort         = "ctrl+c"
)

// backHelp is what the help bar shows for every field's "previous" binding.
const backHelp = keyPrevField + "/" + keyBackAnywhere + "/" + keyBackAlternate

// classifyKey reports whether a key press means "leave this form backwards".
//
// esc is the one key with an exception: huh gives it to Select and MultiSelect
// to clear an open filter, and clearing beats leaving. ctrl+b has no such
// conflict, so it means back even while a filter is open.
func classifyKey(k string, atFirstField, selectFilterOpen bool) bool {
	switch k {
	case keyBackAnywhere:
		return !selectFilterOpen
	case keyBackAlternate:
		return true
	case keyPrevField:
		// Anywhere else huh has an earlier field to move to, so let it.
		return atFirstField
	default:
		return false
	}
}

// stepGroup is a huh group plus the two things huh does not expose: the fields
// it was built from and whether it is hidden. The back keys need both to work
// out which field sits at the top of the form.
type stepGroup struct {
	g      *huh.Group
	fields []huh.Field
	hidden func() bool
}

// newStepGroup mirrors huh.NewGroup.
func newStepGroup(fields ...huh.Field) *stepGroup {
	return &stepGroup{g: huh.NewGroup(fields...), fields: fields}
}

// Title mirrors huh.Group.Title.
func (sg *stepGroup) Title(title string) *stepGroup {
	sg.g = sg.g.Title(title)
	return sg
}

// WithHideFunc mirrors huh.Group.WithHideFunc, keeping the predicate so
// firstVisibleField can ask it again later.
func (sg *stepGroup) WithHideFunc(hide func() bool) *stepGroup {
	sg.hidden = hide
	sg.g = sg.g.WithHideFunc(hide)
	return sg
}

// group is the huh group to hand to huh.NewForm.
func (sg *stepGroup) group() *huh.Group { return sg.g }

// firstVisibleField is the field the cursor sits on when a form opens: the
// first field of the first group that is not hidden. The hide predicates close
// over the wizard's state and their answers change as the user walks around,
// so this is evaluated on every call and never cached. It returns nil when
// every group is hidden, which no current form does.
func firstVisibleField(groups []*stepGroup) huh.Field {
	for _, sg := range groups {
		if sg.hidden != nil && sg.hidden() {
			continue
		}
		if len(sg.fields) > 0 {
			return sg.fields[0]
		}
	}
	return nil
}

// stepForm is a huh form that a step sequence can leave backwards. It keeps
// the groups it was built from, so the back keys can tell where the cursor is,
// and the keymap instance it gave huh, so it can tell whether a select filter
// is open.
type stepForm struct {
	form   *huh.Form
	groups []*stepGroup
	keymap *huh.KeyMap
	// back records that this run is ending because the user asked to go back,
	// which is how a back request is told apart from a real ctrl+c abort: huh
	// reports both as ErrUserAborted. Reset before every run.
	back bool
}

// newStepForm mirrors huh.NewForm over stepGroups.
func newStepForm(groups ...*stepGroup) *stepForm {
	hg := make([]*huh.Group, len(groups))
	for i, sg := range groups {
		hg[i] = sg.group()
	}
	km := wizardKeyMap()
	return &stepForm{
		form:   huh.NewForm(hg...).WithKeyMap(km),
		groups: groups,
		keymap: km,
	}
}

// filterKey is the decision the bubbletea filter makes about one key press: the
// message to hand on to huh, and whether this press ends the form backwards.
//
// It is pure so it can be tested without a terminal; runStep supplies the two
// booleans from the live form.
func (f *stepForm) filterKey(msg tea.KeyPressMsg, atFirstField, selectFilterOpen bool) (tea.Msg, bool) {
	if !classifyKey(msg.String(), atFirstField, selectFilterOpen) {
		return msg, false
	}
	// shift+tab is deliberately not bound on Quit, so swap in one that is.
	if msg.String() == keyPrevField {
		return tea.KeyPressMsg{Code: tea.KeyEscape}, true
	}
	return msg, true
}

// atFirstField reports whether the cursor sits on the form's first visible
// field, where there is nothing left for huh's own "previous field" to reach.
// huh's fields are pointers that return themselves from Update, so comparing
// identities is sound.
func (f *stepForm) atFirstField() bool {
	first := firstVisibleField(f.groups)
	return first != nil && f.form.GetFocusedField() == first
}

// escTakenBy reports whether the field already has a live use for esc. huh
// gives it to Select and MultiSelect to set or clear an open filter, enabling
// those bindings only while one is live.
//
// The flags have to be read off the field. huh copies the keymap into each
// field by value — `s.keymap = k.Select`, field_select.go:802 — so enabling a
// binding never touches the *huh.KeyMap the form was given, and asking that
// instance would always answer "no filter open".
func escTakenBy(field huh.Field) bool {
	if field == nil {
		return false
	}
	for _, b := range field.KeyBinds() {
		if !b.Enabled() {
			continue
		}
		for _, k := range b.Keys() {
			if k == keyBackAnywhere {
				return true
			}
		}
	}
	return false
}

// selectFilterOpen reports whether the focused field is mid-filter, where esc
// belongs to huh rather than to the wizard.
func (f *stepForm) selectFilterOpen() bool {
	return escTakenBy(f.form.GetFocusedField())
}

func (f *stepForm) resetBack() { f.back = false }

// outcome translates huh's result into the sequence's vocabulary. huh reports a
// back request and a ctrl+c the same way, so only the recorded flag separates
// them.
func (f *stepForm) outcome(err error) error {
	if f.back && errors.Is(err, huh.ErrUserAborted) {
		return errBack
	}
	return err
}

// wizardKeyMap is the keymap for forms that take part in a step sequence. It
// adds the back keys to Quit, so huh runs its own teardown and returns
// ErrUserAborted, which runStep turns into errBack.
//
// The four prompts outside the wizard keep huh's default keymap: they have no
// previous step to reach, and two of them run after files are on disk.
func wizardKeyMap() *huh.KeyMap {
	km := huh.NewDefaultKeyMap()
	km.Quit = key.NewBinding(key.WithKeys(keyAbort, keyBackAnywhere, keyBackAlternate))

	// huh labels the multi-select toggle "x", hiding the obvious key on a list
	// of checkboxes. Both stay bound.
	km.MultiSelect.Toggle = key.NewBinding(
		key.WithKeys("space", "x"),
		key.WithHelp("space", "toggle"),
	)

	// Advertise every way back in the help bar huh already renders.
	for _, prev := range []*key.Binding{
		&km.Input.Prev,
		&km.Text.Prev,
		&km.Select.Prev,
		&km.MultiSelect.Prev,
		&km.Confirm.Prev,
		&km.Note.Prev,
		&km.FilePicker.Prev,
	} {
		prev.SetHelp(backHelp, "back")
	}
	return km
}
