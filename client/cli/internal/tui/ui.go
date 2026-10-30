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
	// ModeReconfigure is an existing install the user chose to edit: the forms
	// open pre-filled with the current values.
	ModeReconfigure
	// ModeKeep is an existing install the user chose to leave as-is: the forms
	// are skipped and only config.yaml is regenerated.
	ModeKeep
)

// UI is the interactive seam. The pipeline asks questions; the adapter decides
// how to ask. Real runs use the terminal; tests inject a stub.
type UI interface {
	SelectStateAction() (Mode, error)
	Configure(mode Mode, s *state.State) error
	// RotateSecrets offers the secrets already present in the env files and
	// returns the keys the user wants regenerated. An empty return keeps them
	// all. Only called when an existing install has secrets to offer.
	RotateSecrets(found []Secret) (rotate []string, err error)
	RunDocker() (bool, error)
}

// Secret is one rotatable value: its env-var key and a human label. Defined here
// (not in render) so the pipeline can pass render.LoadSecrets' result to the UI
// without tui importing render.
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
