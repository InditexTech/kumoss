// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

import (
	"os"

	"gopkg.in/yaml.v3"
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

// Load reads a kumoss.yaml into a State. Missing secrets are expected: they are
// yaml:"-" and never persisted, so the caller re-collects them through the
// forms or keeps the existing env files.
func Load(path string) (*State, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var s State
	if err := yaml.Unmarshal(raw, &s); err != nil {
		return nil, err
	}
	return &s, nil
}

// Save writes the non-secret state to path. Fields tagged yaml:"-" (Cloud,
// Engine, Secrets, and every credential map) are dropped by the marshal, so the
// file never carries a secret. Written 0600: it is configuration, not a secret,
// but it names the buckets and providers of this install.
func Save(path string, s *State) error {
	raw, err := yaml.Marshal(s)
	if err != nil {
		return err
	}
	return os.WriteFile(path, raw, 0o600)
}
