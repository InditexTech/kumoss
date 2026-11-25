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
	// model, fields, console question, console keys.
	if len(steps) != 4 {
		t.Fatalf("stateSteps = %d steps, want 4", len(steps))
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
	// LLM 7, Git 1, State 4, Cloud 1, Engine 1, Notifications 1: the order
	// Configure has always asked them in, now as one flat list so that going
	// back at the top of a section reaches the last form of the one before.
	if got := len(w.allSteps()); got != 15 {
		t.Errorf("allSteps = %d steps, want 15", got)
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

func TestStateStepsAskTheConsoleOnlyForTheBundledStore(t *testing.T) {
	cases := []struct {
		model string
		want  bool
	}{
		{"bundled", true},
		{"external_s3", false},
		{"external_azure", false},
		{"repository", false},
	}
	for _, c := range cases {
		w, _ := stubWizard()
		s := &state.State{Storage: state.Storage{Model: c.model, Credentials: map[string]string{}}}
		steps := w.stateSteps()

		err := steps[2](s) // the console question
		ran := !errors.Is(err, errSkip)
		if err != nil && !errors.Is(err, errSkip) {
			t.Fatalf("%s: console step returned %v", c.model, err)
		}
		if ran != c.want {
			t.Errorf("%s: console step ran = %v, want %v", c.model, ran, c.want)
		}
	}
}

func TestConsoleDefaultsToEnabled(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{Storage: state.Storage{Model: "bundled", Credentials: map[string]string{}}}

	if err := w.stateSteps()[2](s); err != nil {
		t.Fatalf("console step returned %v", err)
	}
	if !s.Storage.ConsoleEnabled {
		t.Error("the console question did not default to enabled")
	}
}

func TestConsoleKeysAskedOnlyWhenEnabled(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{Storage: state.Storage{Model: "bundled", ConsoleEnabled: false}}
	if err := w.stateSteps()[3](s); !errors.Is(err, errSkip) {
		t.Errorf("key step returned %v with the console off, want errSkip", err)
	}

	s.Storage.ConsoleEnabled = true
	if err := w.stateSteps()[3](s); err != nil {
		t.Errorf("key step returned %v with the console on, want it to run", err)
	}
}

func TestConsoleKeysSeedTheContainerDefaults(t *testing.T) {
	w, _ := stubWizard()
	s := &state.State{Storage: state.Storage{Model: "bundled", ConsoleEnabled: true}}

	if err := w.stateSteps()[3](s); err != nil {
		t.Fatalf("key step returned %v", err)
	}
	// RustFS falls back to rustfsadmin when the variables are absent, so an
	// unanswered form must not leave them blank and silently disagree.
	if s.Secrets.RustFSAccessKey == "" || s.Secrets.RustFSSecretKey == "" {
		t.Errorf("keys = %q/%q, want the container's defaults seeded",
			s.Secrets.RustFSAccessKey, s.Secrets.RustFSSecretKey)
	}
}
