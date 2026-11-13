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

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/source"
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

	Download *render.Download
	Docker   *docker.Compose
	Out      io.Writer
	Warn     io.Writer
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

	dl := opts.Download
	if dl == nil {
		dl = &render.Download{Fetch: (&source.Fetcher{}).Fetch, Tag: buildinfo.KumossTag()}
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

	samples, err := render.FetchSamples(ctx, dl)
	if err != nil {
		warn(opts.Warn, "could not fetch the env samples (%v); falling back to the built-in key list", err)
	}

	// Render everything first: a diff with a half-built file is worse than none.
	stateBefore, err := state.Render(old)
	if err != nil {
		return err
	}
	stateAfter, err := state.Render(s)
	if err != nil {
		return err
	}
	raw, err := os.ReadFile(opts.Home.ConfigExample())
	if err != nil {
		return fmt.Errorf("read %s: %w", opts.Home.ConfigExample(), err)
	}
	configBefore, err := render.RenderConfig(raw, old)
	if err != nil {
		return err
	}
	configAfter, err := render.RenderConfig(raw, s)
	if err != nil {
		return err
	}
	env := &render.Env{Samples: samples}
	envBefore := env.Files(paths, old.Copy())
	envAfter := env.Files(paths, s)

	diff := diffReport(
		[]fileDiff{
			{opts.Home.StateFile(), string(stateBefore), string(stateAfter)},
			{opts.Home.ConfigYAML(), string(configBefore), string(configAfter)},
			{paths.Core, string(render.RenderEnvFile(envBefore[paths.Core])), string(render.RenderEnvFile(envAfter[paths.Core]))},
			{paths.IAC, string(render.RenderEnvFile(envBefore[paths.IAC])), string(render.RenderEnvFile(envAfter[paths.IAC]))},
			{paths.Notifications, string(render.RenderEnvFile(envBefore[paths.Notifications])), string(render.RenderEnvFile(envAfter[paths.Notifications]))},
		}, section.Services)

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

	c := opts.Docker
	if c == nil {
		c = &docker.Compose{
			ProjectDir: opts.Home.Root,
			Files:      []string{rel(opts.Home.Root, opts.Home.ComposeFile()), rel(opts.Home.Root, opts.Home.ComposeOverride())},
		}
	}
	// A container whose definition changed only starts with the new one when
	// it is force-recreated: `up -d` compares the service definition, and a
	// rewritten env_file or mount is not part of it.
	recreate := section.Services
	if !sameDefinition(opts.Home, s, old) {
		recreate = allServices
	}
	if err := c.Recreate(ctx, recreate...); err != nil {
		return err
	}
	_, err = fmt.Fprintf(out, "Wrote the files and recreated %v.\n", recreate)
	return err
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

// writeDiff prints the changed lines. Values are compared as rendered text, so
// a changed key shows both sides; secrets are masked on the way out.
func writeDiff(w io.Writer, before, after string) {
	old := map[string]string{}
	for _, line := range maskLines(before) {
		old[keyOf(line)] = line
	}
	for _, line := range maskLines(after) {
		if was, ok := old[keyOf(line)]; ok && was == line {
			continue
		}
		if was, ok := old[keyOf(line)]; ok {
			fmt.Fprintf(w, "- %s\n", was)
		}
		fmt.Fprintf(w, "+ %s\n", line)
	}
}
