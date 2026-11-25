// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
	"testing"

	"charm.land/huh/v2"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// stubWizard returns a wizard whose forms never reach a terminal: every run
// returns the next error from results, nil once the list runs out.
func stubWizard(results ...error) (*Wizard, *int) {
	runs := 0
	w := &Wizard{}
	w.runForm = func(*stepForm) error {
		defer func() { runs++ }()
		if runs < len(results) {
			return results[runs]
		}
		return nil
	}
	return w, &runs
}

func TestFormStepCommitsOnBack(t *testing.T) {
	w, _ := stubWizard(errBack)
	committed := false
	build := func(*state.State) (*stepForm, func()) {
		return newStepForm(newStepGroup(huh.NewInput())), func() { committed = true }
	}

	err := w.formStep(build, &state.State{})

	if !errors.Is(err, errBack) {
		t.Fatalf("formStep returned %v, want errBack", err)
	}
	// Leaving a form backwards must keep what was typed in it, or walking back
	// to fix one answer would silently drop another.
	if !committed {
		t.Error("the commit did not run on errBack, so the form's answers were lost")
	}
}

func TestFormStepSkipsCommitOnRealError(t *testing.T) {
	w, _ := stubWizard(huh.ErrUserAborted)
	committed := false
	build := func(*state.State) (*stepForm, func()) {
		return newStepForm(newStepGroup(huh.NewInput())), func() { committed = true }
	}

	err := w.formStep(build, &state.State{})

	if !errors.Is(err, huh.ErrUserAborted) {
		t.Fatalf("formStep returned %v, want huh.ErrUserAborted", err)
	}
	if committed {
		t.Error("the commit ran on a real abort, want it skipped")
	}
}

func TestFormStepCommitsOnSuccess(t *testing.T) {
	w, _ := stubWizard()
	committed := false
	build := func(*state.State) (*stepForm, func()) {
		return newStepForm(newStepGroup(huh.NewInput())), func() { committed = true }
	}

	if err := w.formStep(build, &state.State{}); err != nil {
		t.Fatalf("formStep returned %v, want nil", err)
	}
	if !committed {
		t.Error("the commit did not run on success")
	}
}

func TestStateStepsOrder(t *testing.T) {
	w, _ := stubWizard()
	steps := w.stateSteps()
	if len(steps) != 2 {
		t.Fatalf("stateSteps = %d steps, want 2", len(steps))
	}

	s := &state.State{}
	// The model is picked first, because the fields below it depend on which
	// model was chosen.
	if err := steps[0](s); err != nil {
		t.Fatalf("storage model step returned %v", err)
	}
	if s.Storage.Model == "" {
		t.Error("the first step did not pick a storage model")
	}
	if s.Storage.Provider != "" {
		t.Error("the first step already set the provider, so it is not the model step")
	}
	if err := steps[1](s); err != nil {
		t.Fatalf("storage fields step returned %v", err)
	}
	if s.Storage.Provider == "" {
		t.Error("the second step did not set the provider from the picked model")
	}
}

func TestSingleFormSectionsHaveOneStep(t *testing.T) {
	w, _ := stubWizard()
	for name, steps := range map[string][]step{
		"git":           w.gitSteps(),
		"cloud":         w.cloudSteps(),
		"engine":        w.engineSteps(),
		"notifications": w.notifySteps(),
	} {
		if len(steps) != 1 {
			t.Errorf("%sSteps = %d steps, want 1", name, len(steps))
		}
	}
}

func TestAllStepsConcatenatesSectionsInOrder(t *testing.T) {
	w, _ := stubWizard()
	// LLM 7, Git 1, State 2, Cloud 1, Engine 1, Notifications 1: the order
	// Configure has always asked them in, now as one flat list so that going
	// back at the top of a section reaches the last form of the one before.
	if got := len(w.allSteps()); got != 13 {
		t.Errorf("allSteps = %d steps, want 13", got)
	}
}

func TestConfigureModeKeepRunsNothing(t *testing.T) {
	w, runs := stubWizard()
	if err := w.Configure(ModeKeep, &state.State{}); err != nil {
		t.Fatalf("Configure returned %v, want nil", err)
	}
	if *runs != 0 {
		t.Errorf("ModeKeep ran %d forms, want 0", *runs)
	}
}
