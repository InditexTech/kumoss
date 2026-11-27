// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// step is one form in the wizard. It returns errSkip when it does not apply to
// the answers given so far, errBack when the user asked for the previous step,
// nil when the form was submitted, and any other error to abort the wizard.
type step func(*state.State) error

var (
	// errSkip means this step has nothing to ask for the current answers, so
	// the driver moves on without showing it.
	errSkip = errors.New("step does not apply")
	// errBack means the user pressed one of the back keys.
	errBack = errors.New("back to the previous step")
)

// clearTerminal wipes the screen, parks the cursor at the top and drops the
// scrollback. huh leaves each finished form printed where it ran, so without
// this a reopened form would stack under the copy the user already answered.
func clearTerminal(out io.Writer) { fmt.Fprint(out, "\x1b[H\x1b[2J\x1b[3J") }

// clearBack wipes the screen before a reopened form is drawn.
func (w *Wizard) clearBack() {
	if w.clearScreen != nil {
		w.clearScreen()
		return
	}
	// Accessible mode is a plain line-by-line transcript; clearing it would
	// destroy the record a screen reader just read out.
	if w.Accessible {
		return
	}
	out := w.Out
	if out == nil {
		out = os.Stdout
	}
	clearTerminal(out)
}

// runSequence walks steps, honouring back and skip. The step list is flat: the
// wizard concatenates every section's steps, so going back at the top of one
// section reaches the last form of the one before it.
func (w *Wizard) runSequence(s *state.State, steps []step) error {
	// dir is the way the walk is currently going. It only matters for skipping:
	// a step that does not apply must be stepped over in the direction of
	// travel, or walking backwards would stall on it.
	dir := 1
	for i := 0; i < len(steps); {
		err := steps[i](s)
		switch {
		case err == nil:
			dir = 1
			i++
		case errors.Is(err, errBack):
			dir = -1
			i--
			w.clearBack()
		case errors.Is(err, errSkip):
			i += dir
		default:
			return err
		}
		// There is nothing before the first step, so a back request there
		// reopens it. Turning around also keeps an opening run of
		// inapplicable steps from walking off the front for ever.
		if i < 0 {
			i, dir = 0, 1
		}
	}
	return nil
}
