// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
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

// ProviderEnvKeys is EnvKeys for a state. The provider is re-derived by
// state.Load, so the stored field is always set here.
func ProviderEnvKeys(s *state.State) []string {
	return EnvKeys(s.LLM.Provider)
}
