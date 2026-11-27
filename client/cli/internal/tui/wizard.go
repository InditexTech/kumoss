// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

// run shows a form that stands on its own: the prompts the pipeline asks
// outside the wizard's step sequence. They have no previous step to reach and
// two of them run after files are on disk, so no back key is bound here and
// ctrl+b keeps moving the cursor left inside their inputs.
func (w *Wizard) run(f *huh.Form) error {
	if w.Accessible {
		f = f.WithAccessible(true).WithInput(w.In).WithOutput(w.Out)
	}
	return f.Run()
}

// runStep shows one form of a step sequence, returning errBack when the user
// asked for the previous step.
//
// The back keys are bound on huh's Quit, so huh does its own teardown and
// reports ErrUserAborted; a bubbletea filter, which sees every key before huh
// does, records whether this exit was a back request and converts a shift+tab
// pressed at the top of the form into a key Quit binds.
func (w *Wizard) runStep(f *stepForm) error {
	if w.Accessible {
		// Accessible mode walks every field over plain line I/O and handles no
		// keys at all, so there is nothing to hook and no way back.
		return f.form.WithAccessible(true).WithInput(w.In).WithOutput(w.Out).Run()
	}
	f.resetBack()
	form := f.form.WithProgramOptions(tea.WithFilter(func(_ tea.Model, msg tea.Msg) tea.Msg {
		press, ok := msg.(tea.KeyPressMsg)
		if !ok {
			return msg
		}
		out, back := f.filterKey(press, f.atFirstField(), f.selectFilterOpen())
		if back {
			f.back = true
		}
		return out
	}))
	return f.outcome(form.Run())
}
