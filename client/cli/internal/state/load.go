// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

import (
	"fmt"
)

func Load(path string) (a State, warnings []string, err error) {
	return a, warnings, fmt.Errorf("not implemented")
}

func resolveEnvRefs(a *State) (warnings []string, err error) {
	// Implement environment variable resolution logic here
	return warnings, nil
}
