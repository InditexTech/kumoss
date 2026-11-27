// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"bytes"
	"errors"
	"reflect"
	"testing"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// recorder builds steps that append their index to visits and return the
// errors listed for them, one per call, nil once the list runs out.
type recorder struct {
	visits []int
}

func (r *recorder) step(idx int, errs ...error) step {
	calls := 0
	return func(*state.State) error {
		r.visits = append(r.visits, idx)
		defer func() { calls++ }()
		if calls < len(errs) {
			return errs[calls]
		}
		return nil
	}
}

// always returns a step that returns err on every call.
func (r *recorder) always(idx int, err error) step {
	return func(*state.State) error {
		r.visits = append(r.visits, idx)
		return err
	}
}

func TestRunSequenceVisitsEveryStepInOrder(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0), r.step(1), r.step(2)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	if want := []int{0, 1, 2}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceBackReopensPreviousStep(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0), r.step(1, errBack), r.step(2)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	if want := []int{0, 1, 0, 1, 2}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceBackAtFirstStepReopensIt(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0, errBack), r.step(1)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	if want := []int{0, 0, 1}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceSkipKeepsMovingForward(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0), r.always(1, errSkip), r.step(2)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	if want := []int{0, 1, 2}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceSkipKeepsMovingBackward(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0), r.always(1, errSkip), r.step(2, errBack)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	// Walking back from step 2 passes through the skipped step 1 and lands on
	// step 0, rather than stalling on the step that does not apply.
	if want := []int{0, 1, 2, 1, 0, 1, 2}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceSkipAtLastStepFinishes(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0), r.step(1), r.always(2, errSkip)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	if want := []int{0, 1, 2}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceSkipAtFirstStepGoingBack(t *testing.T) {
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.always(0, errSkip), r.step(1, errBack)})
	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	// Step 0 never applies, so walking back from step 1 clamps at the start and
	// turns around, reopening step 1 instead of indexing below zero.
	if want := []int{0, 1, 0, 0, 1}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceRealErrorAborts(t *testing.T) {
	boom := errors.New("boom")
	r := &recorder{}
	err := newWizard().runSequence(&state.State{}, []step{r.step(0), r.step(1, boom), r.step(2)})
	if !errors.Is(err, boom) {
		t.Fatalf("runSequence returned %v, want %v", err, boom)
	}
	if want := []int{0, 1}; !reflect.DeepEqual(r.visits, want) {
		t.Errorf("visits = %v, want %v", r.visits, want)
	}
}

func TestRunSequenceClearsTheScreenOnBack(t *testing.T) {
	r := &recorder{}
	cleared := 0
	w := &Wizard{clearScreen: func() { cleared++ }}

	err := w.runSequence(&state.State{}, []step{r.step(0), r.step(1, errBack), r.step(2)})

	if err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	// Reopening a form must not stack it under the copy the user already
	// answered, so each back wipes the screen first.
	if cleared != 1 {
		t.Errorf("cleared the screen %d times, want 1", cleared)
	}
}

func TestRunSequenceClearsOnBackAtTheFirstStep(t *testing.T) {
	r := &recorder{}
	cleared := 0
	w := &Wizard{clearScreen: func() { cleared++ }}

	if err := w.runSequence(&state.State{}, []step{r.step(0, errBack), r.step(1)}); err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	// Step 0 reopens itself, which duplicates it on screen just the same.
	if cleared != 1 {
		t.Errorf("cleared the screen %d times, want 1", cleared)
	}
}

func TestRunSequenceDoesNotClearGoingForward(t *testing.T) {
	r := &recorder{}
	cleared := 0
	w := &Wizard{clearScreen: func() { cleared++ }}

	if err := w.runSequence(&state.State{}, []step{r.step(0), r.step(1), r.step(2)}); err != nil {
		t.Fatalf("runSequence returned %v, want nil", err)
	}
	// Walking forward leaves the answered forms on screen as a transcript.
	if cleared != 0 {
		t.Errorf("cleared the screen %d times going forward, want 0", cleared)
	}
}

func TestClearTerminalWritesTheEscapeSequence(t *testing.T) {
	var buf bytes.Buffer
	clearTerminal(&buf)
	// Home, clear screen, clear scrollback: without the last one the old forms
	// are still there on a scroll up.
	if got, want := buf.String(), "\x1b[H\x1b[2J\x1b[3J"; got != want {
		t.Errorf("clearTerminal wrote %q, want %q", got, want)
	}
}

// newWizard is a wizard whose screen clearing is a no-op, so the driver tests
// never write escape sequences into the test output.
func newWizard() *Wizard { return &Wizard{clearScreen: func() {}} }
