// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"slices"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// EnvKeys returns the environment variable names a provider's credential
// fields use, so `kumoss status` can report which are set without reading the
// .env files itself.
func EnvKeys(provider string) []string {
	idx := providerIndex(provider)
	if idx < 0 {
		return nil
	}
	keys := make([]string, len(llmProviders[idx].Credentials))
	for i, c := range llmProviders[idx].Credentials {
		keys[i] = c.Name
	}
	return keys
}

// ProviderEnvKeys is EnvKeys for a state, for every picked provider: two of them
// mean two credential sets the core reads at boot.
func ProviderEnvKeys(s *state.State) []string {
	var keys []string
	for _, prefix := range s.LLM.Providers {
		keys = append(keys, EnvKeys(prefix)...)
	}
	return keys
}

// RequiredEnvKeys is ProviderEnvKeys without the variables a blank value is a
// supported answer for, so `kumoss run` blocks only on a credential whose
// absence really stops the stack.
func RequiredEnvKeys(s *state.State) []string {
	var keys []string
	for _, key := range ProviderEnvKeys(s) {
		if optionalCredentials[key] {
			continue
		}
		if !slices.Contains(keys, key) {
			keys = append(keys, key)
		}
	}
	return keys
}
