// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

import (
	"os"
	"path/filepath"

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

// Load reads a kumoss.yaml into a State. Missing secrets are expected: they
// are never persisted, so the caller re-collects or keeps the env files.
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

// Save writes the non-secret state. The yaml:"-" fields are dropped by the
// marshal, so the file carries no secret. 0600 anyway: it names this
// install's buckets and providers.
func Save(path string, s *State) error {
	raw, err := Render(s)
	if err != nil {
		return err
	}
	// Same temp-then-rename as render.writeFile, which is unexported here. A
	// torn kumoss.yaml would lose every answer.
	tmp, err := os.CreateTemp(filepath.Dir(path), ".kumoss.yaml.*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(raw); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

// Render returns the bytes Save would write, for a dry run.
func Render(s *State) ([]byte, error) {
	return yaml.Marshal(s)
}
