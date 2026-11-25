// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// LLM asks the providers, the models, the knobs and every provider's
// credentials.
func (w *Wizard) LLM(s *state.State) error { return w.runSequence(s, w.llmSteps()) }

// Git asks the push provider, the author identity and the credentials.
func (w *Wizard) Git(s *state.State) error { return w.runSequence(s, w.gitSteps()) }

// Cloud asks the credential group of each picked cloud.
func (w *Wizard) Cloud(s *state.State) error { return w.runSequence(s, w.cloudSteps()) }

// Engine asks OpenTofu or Terraform.
func (w *Wizard) Engine(s *state.State) error { return w.runSequence(s, w.engineSteps()) }

// State asks the storage model and the state backend.
func (w *Wizard) State(s *state.State) error { return w.runSequence(s, w.stateSteps()) }

// Notifications asks for the Slack webhook and whether to use it.
func (w *Wizard) Notifications(s *state.State) error { return w.runSequence(s, w.notifySteps()) }

func (w *Wizard) gitSteps() []step {
	return []step{func(s *state.State) error { return w.formStep(w.gitStep, s) }}
}

func (w *Wizard) cloudSteps() []step {
	return []step{func(s *state.State) error { return w.formStep(w.cloudStep, s) }}
}

func (w *Wizard) engineSteps() []step {
	return []step{func(s *state.State) error { return w.formStep(w.engineStep, s) }}
}

func (w *Wizard) notifySteps() []step {
	return []step{func(s *state.State) error { return w.formStep(w.notificationsStep, s) }}
}

// stateSteps splits the model from its settings: the fields below depend on
// which model was picked, and huh cannot add fields to a running form.
func (w *Wizard) stateSteps() []step {
	return []step{
		w.storageModelStep,
		func(s *state.State) error { return w.formStep(w.storageStep, s) },
	}
}

// formStep runs one form and its commit, the shape every section shares.
//
// The commit also runs when the user leaves backwards: several forms bind
// their fields to locals and copy them into the state only once the form
// returns, so skipping it would throw away whatever was typed into the form
// being left. Every local is seeded from the state when the form is built, so
// committing a field the user never reached writes back what it already held.
func (w *Wizard) formStep(build func(*state.State) (*stepForm, func()), s *state.State) error {
	form, commit := build(s)
	err := w.execStep(form)
	if err == nil || errors.Is(err, errBack) {
		commit()
	}
	return err
}
