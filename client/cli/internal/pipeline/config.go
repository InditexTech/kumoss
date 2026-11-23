// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package pipeline

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// ConfigOptions is the resolved input to RunConfig.
type ConfigOptions struct {
	Home home.Home
	// Section is the name of the one section to edit.
	Section string

	UI SectionUI
	// Confirm asks before writing. Tests pass a stub; nil asks nothing and
	// writes, since the command always confirms first.
	Confirm func(diff string) (bool, error)

	// Docker is the stack. nil builds the real runner; tests inject a stub.
	Docker docker.Runner
	Out    io.Writer
	Warn   io.Writer
}

// RunConfig reopens one section, shows what would change with the secrets
// masked, and on confirmation writes the files and recreates only the
// containers that read them.
func RunConfig(ctx context.Context, opts ConfigOptions) error {
	section := SectionByName(opts.Section)
	if section == nil {
		return fmt.Errorf("unknown section %q", opts.Section)
	}
	if _, err := os.Stat(opts.Home.StateFile()); err != nil {
		return fmt.Errorf("no install at %s; run kumoss init first", opts.Home.Root)
	}
	out := opts.Out
	if out == nil {
		out = io.Discard
	}

	old, err := state.Load(opts.Home.StateFile())
	if err != nil {
		return err
	}
	s := old.Copy()

	// The sections read the values the env files hold, not the empty yaml
	// fields: the tokens and the cloud answers only live there. A kept token
	// carries over unchanged, so the diff shows only what this edit changes.
	paths := envPaths(opts.Home)
	existing, _ := render.LoadSecrets(paths)
	render.Fill(s, existing, nil)
	render.Fill(old, existing, nil)
	render.FillCloud(s, paths)
	render.FillCloud(old, paths)
	fillEnvOnly(s, paths)
	fillEnvOnly(old, paths)

	// A state change does not migrate what is already stored, and the new
	// backend would look empty. Say so before asking, not after writing.
	if section.Name == "state" {
		fmt.Fprintln(out, "Warning: changing the state backend does not migrate the existing state.")
		fmt.Fprintln(out, "Terraform will not find it in the new backend and will offer to create everything again.")
	}

	if err := section.Ask(opts.UI, s); err != nil {
		return err
	}

	// Same gate as init: the service refuses to boot without a webhook.
	if s.Notifications.Enabled && s.Notifications.SlackWebhookURL == "" {
		s.Notifications.Enabled = false
		warn(opts.Warn, "notifications disabled: no Slack webhook URL given")
	}

	// The key set comes from the env files on disk, not the repo's samples:
	// config edits an install that is already there, so it must work offline.
	env := &render.Env{Samples: localSamples(paths)}
	envBefore := env.Files(paths, old.Copy())
	envAfter := env.Files(paths, s)

	// Render everything first: a diff with a half-built file is worse than none.
	stateBefore, err := state.Render(old)
	if err != nil {
		return err
	}
	stateAfter, err := state.Render(s)
	if err != nil {
		return err
	}
	// Render from the config.yaml the user actually runs, not the shipped
	// copy: overlay keeps every key the forms do not own, so seeding it from
	// the defaults would revert the hand-edited ones — including oidc, whose
	// blank issuer_url turns authentication off.
	raw, err := os.ReadFile(opts.Home.ConfigYAML())
	if err != nil {
		return fmt.Errorf("read %s: %w", opts.Home.ConfigYAML(), err)
	}
	configBefore, err := render.RenderConfig(raw, old)
	if err != nil {
		return err
	}
	configAfter, err := render.RenderConfig(raw, s)
	if err != nil {
		return err
	}

	// The override carries the credential mounts, so a cloud edit has to
	// rewrite it. Without the new mount, a recreated container still lacks the
	// credential file its env var points at.
	overrideBefore, err := renderCompose(opts.Home, old, false)
	if err != nil {
		return err
	}
	overrideAfter, err := renderCompose(opts.Home, s, false)
	if err != nil {
		return err
	}

	recreate := section.Services
	if !sameDefinition(opts.Home, s, old) {
		recreate = allServices
	}

	diff := diffReport(
		[]fileDiff{
			{opts.Home.StateFile(), string(stateBefore), string(stateAfter)},
			{opts.Home.ConfigYAML(), string(configBefore), string(configAfter)},
			{paths.Core, string(render.RenderEnvFile(envBefore[paths.Core])), string(render.RenderEnvFile(envAfter[paths.Core]))},
			{paths.IAC, string(render.RenderEnvFile(envBefore[paths.IAC])), string(render.RenderEnvFile(envAfter[paths.IAC]))},
			{paths.Notifications, string(render.RenderEnvFile(envBefore[paths.Notifications])), string(render.RenderEnvFile(envAfter[paths.Notifications]))},
			{opts.Home.ComposeOverride(), string(overrideBefore), string(overrideAfter)},
		}, recreate)

	if opts.Confirm != nil {
		ok, err := opts.Confirm(diff)
		if err != nil {
			return err
		}
		if !ok {
			fmt.Fprintln(out, "Aborted; nothing was written.")
			return nil
		}
	} else {
		fmt.Fprint(out, diff)
	}

	if err := state.Save(opts.Home.StateFile(), s); err != nil {
		return err
	}
	if err := render.WriteConfig(opts.Home.ConfigYAML(), configAfter); err != nil {
		return err
	}
	if err := env.Write(paths, s); err != nil {
		return err
	}
	if string(overrideBefore) != string(overrideAfter) {
		// Only when the mounts changed: the override may hold host-certs
		// wiring this command never asked about, and rewriting it wholesale
		// would silently drop that.
		if err := os.WriteFile(opts.Home.ComposeOverride(), overrideAfter, 0o644); err != nil {
			return err
		}
	}

	c := opts.Docker
	if c == nil {
		c = docker.NewCompose(opts.Home)
	}
	// A container whose definition changed only starts with the new one when
	// it is force-recreated: `up -d` compares the service definition, and a
	// rewritten env_file or mount is not part of it. Only a home with a compose
	// file has a stack to recreate; an interrupted init may have none, and a
	// missing file would make compose fail after the edits were already written.
	if _, err := os.Stat(opts.Home.ComposeFile()); err == nil {
		if err := c.Recreate(ctx, recreate...); err != nil {
			return err
		}
	}
	_, err = fmt.Fprintf(out, "Wrote the files and recreated %v.\n", recreate)
	return err
}

// localSamples reads the key set from the env files already on disk, so a
// section edit needs no network. The values are dropped on purpose: they must
// not override what the state holds, and the keys are all that matters.
func localSamples(p render.EnvPaths) *render.Samples {
	local := func(path string) *render.Sample {
		vars := render.ReadEnv(path)
		keys := make([]string, 0, len(vars))
		for k := range vars {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		s := &render.Sample{}
		for _, k := range keys {
			s.Vars = append(s.Vars, render.Var{Key: k})
		}
		return s
	}
	return &render.Samples{Core: local(p.Core), IAC: local(p.IAC), Notifications: local(p.Notifications)}
}

// fillEnvOnly restores what kumoss.yaml cannot hold: the values its yaml:"-"
// fields drop that LoadSecrets and FillCloud do not cover. Without it, editing
// one section rewrites all three .env files with those values blank, erasing
// the LLM key, the Git credentials, the storage key and the webhook.
func fillEnvOnly(s *state.State, p render.EnvPaths) {
	core := render.ReadEnv(p.Core)
	iac := render.ReadEnv(p.IAC)
	s.Git.User = first(s.Git.User, core["GIT_USER"])
	s.Git.Token = first(s.Git.Token, core["GIT_TOKEN"])
	s.LLM.Credentials = fillFrom(s.LLM.Credentials, core)
	s.Storage.Credentials = fillFrom(s.Storage.Credentials, core)
	s.Storage.BackendCredentials = fillFrom(s.Storage.BackendCredentials, iac)
	s.Engine.Binary = first(s.Engine.Binary, iac["IAC_BINARY"])
	s.Notifications.SlackWebhookURL = first(s.Notifications.SlackWebhookURL, render.ReadEnv(p.Notifications)["SLACK_WEBHOOK_URL"])
}

// fillFrom copies the env vars m does not already hold, so a key the user
// cleared on purpose in this run stays cleared.
func fillFrom(m, vars map[string]string) map[string]string {
	if len(vars) == 0 {
		return m
	}
	if m == nil {
		m = map[string]string{}
	}
	for k, v := range vars {
		if _, ok := m[k]; !ok {
			m[k] = v
		}
	}
	return m
}

func first(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// allServices is every container whose definition the override can change.
// Searxng and the databases are not configurable, so they are left alone.
var allServices = []string{"core", "iac", "notifications"}

// sameDefinition reports whether the answers that change a container's
// definition are unchanged. Anything the override or the service env files
// feed needs the containers replaced, not merely restarted: compose keeps a
// container whose definition it considers identical.
func sameDefinition(h home.Home, a, b *state.State) bool {
	return fmt.Sprint(iacMounts(h, a)) == fmt.Sprint(iacMounts(h, b)) &&
		a.Engine.Binary == b.Engine.Binary
}

// fileDiff is one generated file, before and after the edit.
type fileDiff struct {
	path, before, after string
}

// diffReport lists the lines that differ per file, with every secret masked.
// Unchanged files are named as such, so "nothing changed" is visible too.
func diffReport(files []fileDiff, services []string) string {
	var b bytes.Buffer
	for _, f := range files {
		if f.before == f.after {
			fmt.Fprintf(&b, "%s: unchanged\n", f.path)
			continue
		}
		fmt.Fprintf(&b, "%s:\n", f.path)
		writeDiff(&b, f.before, f.after)
	}
	fmt.Fprintf(&b, "\nRecreate: %v\n", services)
	return b.String()
}

// writeDiff prints the changed lines. Lines are paired by key and compared as
// rendered text, so a changed key shows both sides and a removed one shows as
// a "-". Only the printed copy is masked: masking first would hide a rotated
// secret behind two identical <redacted> lines.
func writeDiff(w io.Writer, before, after string) {
	old := map[string]string{}
	var order []string
	for _, line := range strings.Split(strings.TrimRight(before, "\n"), "\n") {
		if _, seen := old[keyOf(line)]; !seen {
			order = append(order, keyOf(line))
		}
		old[keyOf(line)] = line
	}
	for _, line := range strings.Split(strings.TrimRight(after, "\n"), "\n") {
		key := keyOf(line)
		was, existed := old[key]
		delete(old, key)
		if existed && was == line {
			continue
		}
		if existed {
			fmt.Fprintf(w, "- %s\n", maskLine(was))
		}
		fmt.Fprintf(w, "+ %s\n", maskLine(line))
	}
	for _, key := range order {
		if was, ok := old[key]; ok {
			fmt.Fprintf(w, "- %s\n", maskLine(was))
		}
	}
}
