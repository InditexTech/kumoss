// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import "charm.land/huh/v2"

func (w *Wizard) SelectStateAction() (Mode, error) {
	mode := ModeFresh
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[Mode]().
				Title("There is an existing kumoss.yaml state file. Choose an action").
				Options(
					huh.NewOption("Reconfigure", ModeReconfigure),
					huh.NewOption("Keep it as is and continue", ModeKeep),
				).
				Value(&mode),
		),
	)
	if err := w.run(form); err != nil {
		return ModeFresh, err
	}
	return mode, nil
}
