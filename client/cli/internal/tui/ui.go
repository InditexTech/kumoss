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
	// ExtraVars asks for the sample keys the wizard does not own.
	ExtraVars(keys []Secret) (map[string]string, error)
	// ConfirmRegenerate guards compose.override.yml, which may be hand-edited.
	ConfirmRegenerate(what string) (bool, error)
	RunDocker() (bool, error)
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
}

var _ UI = (*Wizard)(nil) // compile-time check that Wizard satisfies UI
