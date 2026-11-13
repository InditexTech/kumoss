// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// Section is one editable group of answers, the unit of `kumoss config
// <section>`. Services are the containers to recreate, not restart: compose
// compares the service definition, not the bytes of a mounted .env, so a
// restart would keep the old values.
type Section struct {
	Name     string
	Services []string
	// Ask runs the section's forms on s. Returned errors abort the edit.
	Ask func(ui SectionUI, s *state.State) error
}

// SectionUI is the slice of tui.UI the sections need. Narrow on purpose, so a
// test can stub one section without the whole wizard.
type SectionUI interface {
	LLM(s *state.State) error
	Git(s *state.State) error
	Cloud(s *state.State) error
	Engine(s *state.State) error
	State(s *state.State) error
	Notifications(s *state.State) error
	// RotateSecrets returns the keys to regenerate; empty keeps them all.
	RotateSecrets(found []Secret) ([]string, error)
}

// Secret is one rotatable value, mirroring tui.Secret.
type Secret = tui.Secret

// Sections is the registry, in the order `kumoss config` lists them.
var Sections = []Section{
	{Name: "llm", Services: []string{"core"}, Ask: func(ui SectionUI, s *state.State) error { return ui.LLM(s) }},
	{Name: "git", Services: []string{"core"}, Ask: func(ui SectionUI, s *state.State) error { return ui.Git(s) }},
	{Name: "cloud", Services: []string{"iac"}, Ask: func(ui SectionUI, s *state.State) error { return ui.Cloud(s) }},
	{Name: "engine", Services: []string{"iac"}, Ask: func(ui SectionUI, s *state.State) error { return ui.Engine(s) }},
	{Name: "state", Services: []string{"core", "iac"}, Ask: func(ui SectionUI, s *state.State) error { return ui.State(s) }},
	{Name: "notifications", Services: []string{"core", "notifications"}, Ask: func(ui SectionUI, s *state.State) error { return ui.Notifications(s) }},
	{Name: "secrets", Services: []string{"core", "iac", "notifications"}, Ask: rotateSecrets},
}

// SectionByName returns the section, or nil.
func SectionByName(name string) *Section {
	for i := range Sections {
		if Sections[i].Name == name {
			return &Sections[i]
		}
	}
	return nil
}

// rotateSecrets regenerates the bearer tokens on both sides of each pair. It
// never generates: an empty answer keeps every token, since rotating breaks
// any client holding the old one.
func rotateSecrets(ui SectionUI, s *state.State) error {
	found := []Secret{}
	if s.Secrets.IACToken != "" {
		found = append(found, Secret{Key: "KUMOSS_IAC_TOKEN", Label: "IaC service bearer token"})
	}
	if s.Secrets.NotificationsToken != "" {
		found = append(found, Secret{Key: "KUMOSS_NOTIFICATIONS_TOKEN", Label: "Notifications service bearer token"})
	}
	rotate, err := ui.RotateSecrets(found)
	if err != nil {
		return err
	}
	for _, key := range rotate {
		switch key {
		case "KUMOSS_IAC_TOKEN":
			s.Secrets.IACToken = ""
		case "KUMOSS_NOTIFICATIONS_TOKEN":
			s.Secrets.NotificationsToken = ""
		}
	}
	return nil
}
