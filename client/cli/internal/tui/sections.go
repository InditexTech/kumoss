// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"charm.land/huh/v2"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// LLM asks the provider, the models, the knobs and the credentials.
func (w *Wizard) LLM(s *state.State) error {
	// Split in two: the credential fields depend on the provider picked first.
	idx, err := w.llmProviderStep(s)
	if err != nil {
		return err
	}
	return w.llmDetailsStep(s, providerAt(idx))
}

// Git asks the push provider, the author identity and the credentials.
func (w *Wizard) Git(s *state.State) error { return w.step(w.gitStep, s) }

// Cloud asks the credential group of each picked cloud.
func (w *Wizard) Cloud(s *state.State) error { return w.step(w.cloudStep, s) }

// Engine asks OpenTofu or Terraform.
func (w *Wizard) Engine(s *state.State) error { return w.step(w.engineStep, s) }

// State asks the storage model and the state backend.
func (w *Wizard) State(s *state.State) error { return w.step(w.storageStep, s) }

// Notifications asks for the Slack webhook and whether to use it.
func (w *Wizard) Notifications(s *state.State) error { return w.step(w.notificationsStep, s) }

// step runs one form and its commit, the shape every section shares.
func (w *Wizard) step(build func(*state.State) (*huh.Form, func()), s *state.State) error {
	form, commit := build(s)
	if err := w.run(form); err != nil {
		return err
	}
	commit()
	return nil
}
