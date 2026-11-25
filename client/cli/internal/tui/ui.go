// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"io"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// Mode is what the pipeline does with an existing install.
type Mode int

const (
	// ModeFresh is a new install: the forms open empty.
	ModeFresh Mode = iota
	// ModeReconfigure edits an existing install: the forms open pre-filled.
	ModeReconfigure
	// ModeKeep writes nothing; the pipeline still offers to start the stack.
	ModeKeep
)

// UI is the interactive seam: the pipeline asks, the adapter decides how.
type UI interface {
	SelectStateAction() (Mode, error)
	Configure(mode Mode, s *state.State) error
	// RotateSecrets returns the keys to regenerate; empty keeps them all.
	RotateSecrets(found []Secret) (rotate []string, err error)
	// ConfirmRegenerate guards compose.override.yml, which may be hand-edited.
	ConfirmRegenerate(what string) (bool, error)
	RunDocker() (bool, error)
	// SetDefaults hands the wizard the installed config.yaml, so its forms can
	// pre-fill what the file already holds. Nil means nothing to show.
	SetDefaults(doc map[string]any)
}

// Secret is one rotatable value. Defined here, not in render, so the pipeline
// can pass LoadSecrets' result on without tui importing render.
type Secret struct {
	Key   string // env-var name, e.g. KUMOSS_IAC_TOKEN
	Label string // what it is, e.g. "IaC service bearer token"
}

// Wizard is the terminal implementation. In/Out are the Cobra streams;
// Accessible drives forms through plain line I/O so tests need no TTY.
type Wizard struct {
	In         io.Reader
	Out        io.Writer
	Accessible bool
	// Doc is the installed config.yaml, parsed: the forms pre-fill from it
	// when the state holds no answer of its own.
	Doc map[string]any

	// runForm shows one step form. nil means runStep, the real terminal; the
	// tests substitute a stub, since the step logic cannot be driven through a
	// running huh form.
	runForm func(*stepForm) error
	// clearScreen wipes the terminal before a reopened form is drawn. nil
	// means the real escape sequence; the tests substitute a counter.
	clearScreen func()

	// llmPicked is the select row behind each entry of s.LLM.Providers, in the
	// same order. A prefix cannot name a row on its own: "OpenAI" and
	// "OpenAI-compatible" share "openai", so resolving a stored prefix back
	// through providerIndex would always yield the first of the two and the
	// wizard would ask the wrong defaults and hints. Empty when a reconfigure
	// has not reached the provider form yet, where the prefix is all there is.
	llmPicked []int
}

// execStep runs one step form through the seam runForm provides.
func (w *Wizard) execStep(f *stepForm) error {
	if w.runForm != nil {
		return w.runForm(f)
	}
	return w.runStep(f)
}

// SetDefaults stores the parsed config.yaml for the forms.
func (w *Wizard) SetDefaults(doc map[string]any) { w.Doc = doc }

var _ UI = (*Wizard)(nil) // compile-time check that Wizard satisfies UI
