// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package pipeline runs the `kumoss init` flow: prepare the home skeleton,
// fetch the compose stack, collect configuration, write the state, config and
// env files, and start the containers. It is a plain function so the steps are
// testable without a terminal and reusable outside the Cobra command.
package pipeline

import (
	"fmt"
	"os"

	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// Options is the resolved input to Run.
type Options struct {
	// Home is the resolved managed directory layout.
	Home home.Home

	// PersistHome records the resolved root in the pointer file, so later
	// invocations find it without repeating --home. Set only when the user
	// passed --home explicitly.
	PersistHome bool
	UI          tui.UI
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

	// 2. Check if the state file exists and load it
	var mode tui.Mode

	if exists, err := state.StateFileExist(opts.Home.StateFile()); err != nil {
		return err
	} else if exists {
		if stateFile, err := os.ReadFile(opts.Home.StateFile()); err != nil {
			return err
		} else {
			_ = stateFile
			fmt.Println("kumoss.yaml does exist, state file loaded")
			fmt.Println("state file content:", string(stateFile))

			if mode, err = opts.UI.SelectStateAction(); err != nil {
				return err
			}
			fmt.Println("selected mode:", mode)
		}
	} else {
		fmt.Println("kumoss.yaml does not exist")
		fmt.Println("Selected mode:", mode)

	}

	// 2. Decide what to do with an existing install, then collect answers.
	// mode := ModeFresh
	// exists, err := stateFileExists(opts.Home)
	// if err != nil {
	// 	return err
	// }
	return nil
}
