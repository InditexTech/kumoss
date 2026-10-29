// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

import (
	"os"
)

func StateFileExist(path string) (bool, error) {
	exist, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	return !exist.IsDir(), nil
}

func resolveEnvRefs(a *State) (warnings []string, err error) {
	// Implement environment variable resolution logic here
	return warnings, nil
}
