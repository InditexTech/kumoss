// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package pipeline runs the `kumoss init` flow: prepare the home skeleton,
// fetch the compose stack, collect configuration, write the state, config and
// env files, and start the containers. It is a plain function so the steps are
// testable without a terminal and reusable outside the Cobra command.
package pipeline

import (
	"os"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
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

// Options is the resolved input to Run.
type Options struct {
	// Home is the resolved managed directory layout.
	Home home.Home

	// PersistHome records the resolved root in the pointer file, so later
	// invocations find it without repeating --home. Set only when the user
	// passed --home explicitly.
	PersistHome bool
}

// RunPipeline executes the pipeline top to bottom. Every step is idempotent, so a
// failed run is fixed by running it again.
func RunPipeline(opts Options) error {
	// 1. Ensure the directory skeleton exists.
	if err := opts.Home.Ensure(); err != nil {
		return err
	}
	if opts.PersistHome {
		if err := home.SetPointer(opts.Home.Root); err != nil {
			return err
		}
	}

	// 2. Decide what to do with an existing install, then collect answers.
	// mode := ModeFresh
	// exists, err := stateFileExists(opts.Home)
	// if err != nil {
	// 	return err
	// }
	return nil
}

// stateFileExists reports whether kumoss.yaml is already present.
func stateFileExists(h home.Home) (bool, error) {
	_, err := os.Stat(h.StateFile())
	if err == nil {
		return true, nil
	}
	if os.IsNotExist(err) {
		return false, nil
	}
	return false, err
}
