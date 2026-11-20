// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import "charm.land/huh/v2"

func (w *Wizard) run(f *huh.Form) error {
	if w.Accessible {
		f = f.WithAccessible(true).WithInput(w.In).WithOutput(w.Out)
	}
	return f.Run()
}
