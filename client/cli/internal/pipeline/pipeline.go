// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package pipeline runs the `kumoss init` flow: prepare the home, fetch the
// stack, collect answers, write the files, start the containers. A plain
// function, and every side effect goes through a seam the caller can stub.
package pipeline

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/source"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// Options is the resolved input to RunPipeline.
type Options struct {
	// Home is the resolved managed directory layout.
	Home home.Home

	// PersistHome records the root in the pointer file, so later runs find it
	// without --home. Set only when the user passed the flag.
	PersistHome bool
	UI          tui.UI

	// Download fetches the repo files. nil uses the real fetcher at the release
	// tag; tests inject a stub.
	Download *render.Download

	// Warn receives non-fatal warnings. nil discards them.
	Warn io.Writer

	// Docker starts the stack. nil builds the real runner; tests inject a stub.
	Docker docker.Runner

	// Foreground keeps `up` attached: logs stream until Ctrl-C, which also stops
	// the stack. Detached by default, which is what an installer wants.
	Foreground bool

	// HostCerts wires the host's CA roots into core and searxng, for a
	// TLS-inspecting proxy. Off by default: that directory is usually absent.
	HostCerts bool

	// DryRun prints the files the run would write to Out, and writes nothing.
	DryRun bool

	// Out receives the dry-run report. nil discards it.
	Out io.Writer
}

// RunPipeline runs the steps top to bottom. Every step is idempotent, so a
// failed run is fixed by running it again, and ctx cancellation aborts the
// network steps and a foreground `up`.
//
// With opts.DryRun nothing is written at all; the same wizard runs and the
// files it would write go to opts.Out.
func RunPipeline(ctx context.Context, opts Options) error {
	if opts.DryRun {
		return dryRun(ctx, opts)
	}

	// 1. Ensure the directory skeleton exists.
	if err := opts.Home.Ensure(); err != nil {
		return err
	}
	if opts.PersistHome {
		if err := home.SetPointer(opts.Home.Root); err != nil {
			return err
		}
	}

	dl := opts.download()

	// 2. Fetch the compose file. Skipped if present: it may be hand-edited.
	if err := fetchCompose(ctx, dl, opts.Home.ComposeFile()); err != nil {
		return err
	}

	// 3. An existing kumoss.yaml means asking whether to reconfigure or keep.
	s := &state.State{SchemaVersion: 1}
	mode := tui.ModeFresh

	exists, err := state.StateFileExist(opts.Home.StateFile())
	if err != nil {
		return err
	}
	if exists {
		if s, err = state.Load(opts.Home.StateFile()); err != nil {
			return err
		}
		if mode, err = opts.UI.SelectStateAction(); err != nil {
			return err
		}
	}

	// 4. Fetch the env samples for their key sets. A failure warns rather than
	// stopping: the built-in list still produces a usable file set.
	samples, err := render.FetchSamples(ctx, dl)
	if err != nil {
		warn(opts.Warn, "could not fetch the env samples (%v); falling back to the built-in key list. Review the generated .env files against core/env.sample and services/*/env.sample in the repo, or the documentation.", err)
	}

	// 5. Collect answers. ModeKeep skips the forms entirely.
	if err := opts.UI.Configure(mode, s); err != nil {
		return err
	}

	// 6. Write the two YAML files. ModeKeep writes neither, as promised.
	if mode != tui.ModeKeep {
		// The service refuses to boot without a webhook, so downgrade rather
		// than write a stack that cannot start.
		if s.Notifications.Enabled && s.Notifications.SlackWebhookURL == "" {
			s.Notifications.Enabled = false
			warn(opts.Warn, "notifications disabled: no Slack webhook URL given")
		}
		if err := state.Save(opts.Home.StateFile(), s); err != nil {
			return err
		}
		cfg := &render.Config{
			Download: dl,
			Path:     opts.Home.ConfigYAML(),
			Example:  opts.Home.ConfigExample(),
		}
		if err := cfg.Write(ctx, s); err != nil {
			return err
		}
	}

	// 7. Write the three env files. ModeKeep leaves them alone: they hold the
	// only copy of the secrets. Otherwise reuse them, offering a rotation.
	if mode != tui.ModeKeep {
		paths := envPaths(opts.Home)
		existing, found := render.LoadSecrets(paths)
		var rotate []string
		if found {
			rotate, err = opts.UI.RotateSecrets(existingSecretList(existing))
			if err != nil {
				return err
			}
		}
		// Write then generates fresh values for exactly the rotated keys.
		render.Fill(s, existing, rotate)

		env := &render.Env{Samples: samples}
		if samples != nil {
			// Keys with no value and no owner: only the user can supply them.
			env.Extra, err = opts.UI.ExtraVars(askList(samples, env.OwnedKeys(s)))
			if err != nil {
				return err
			}
		}
		if err := env.Write(paths, s); err != nil {
			return err
		}
	}

	// 8. Write compose.override.yml, which is what points core's config mount
	// at the file written above. Replaced only with consent, since it may have
	// been hand-edited; a fresh install has nothing to ask about.
	if mode != tui.ModeKeep {
		path := opts.Home.ComposeOverride()
		write := true
		if _, err := os.Stat(path); err == nil {
			if write, err = opts.UI.ConfirmRegenerate("compose.override.yml"); err != nil {
				return err
			}
		}
		if write {
			override := &render.Compose{
				Path:       path,
				ConfigPath: "../config/config.yaml",
				HostCerts:  opts.HostCerts,
				Mounts:     iacMounts(opts.Home, s),
			}
			if err := override.Write(); err != nil {
				return err
			}
		}
	}

	// 9. Pull and start. The recreate is what makes a reconfigure take effect:
	// compose compares the service definition, not the bytes of a mounted file,
	// so a plain `up -d` would keep the old containers and the old values.
	run, err := opts.UI.RunDocker()
	if err != nil {
		return err
	}
	if run {
		runner := opts.Docker
		if runner == nil {
			runner = &docker.Compose{
				ProjectDir: opts.Home.Root,
				Files: []string{
					rel(opts.Home.Root, opts.Home.ComposeFile()),
					rel(opts.Home.Root, opts.Home.ComposeOverride()),
				},
			}
		}
		if err := runner.Pull(ctx); err != nil {
			return fmt.Errorf("pull images: %w", err)
		}
		if err := runner.Up(ctx, mode != tui.ModeFresh, !opts.Foreground); err != nil {
			return fmt.Errorf("start the stack: %w", err)
		}
	}

	return nil
}

// download returns the injected fetcher, or the real one at the release tag.
func (o Options) download() *render.Download {
	if o.Download != nil {
		return o.Download
	}
	return &render.Download{Fetch: (&source.Fetcher{}).Fetch, Tag: buildinfo.KumossTag()}
}

// dryRun is RunPipeline with every write replaced by a report: same wizard,
// same state, same fetched defaults — only the side effects differ.
func dryRun(ctx context.Context, opts Options) error {
	dl := opts.download()
	out := opts.Out
	if out == nil {
		out = io.Discard
	}

	s := &state.State{SchemaVersion: 1}
	mode := tui.ModeFresh
	exists, err := state.StateFileExist(opts.Home.StateFile())
	if err != nil {
		return err
	}
	if exists {
		if s, err = state.Load(opts.Home.StateFile()); err != nil {
			return err
		}
		if mode, err = opts.UI.SelectStateAction(); err != nil {
			return err
		}
	}

	samples, err := render.FetchSamples(ctx, dl)
	if err != nil {
		warn(opts.Warn, "could not fetch the env samples (%v); falling back to the built-in key list. Review the generated .env files against core/env.sample and services/*/env.sample in the repo, or the documentation.", err)
	}
	if err := opts.UI.Configure(mode, s); err != nil {
		return err
	}
	if mode == tui.ModeKeep {
		// Keep writes nothing, so there is nothing to preview.
		_, err := fmt.Fprintf(out, "dry run: keeping %s as is; nothing would be written\n", opts.Home.StateFile())
		return err
	}

	// Same gate as the real run, or the preview shows a stack that cannot start.
	if s.Notifications.Enabled && s.Notifications.SlackWebhookURL == "" {
		s.Notifications.Enabled = false
		warn(opts.Warn, "notifications disabled: no Slack webhook URL given")
	}

	raw, err := dl.File(ctx, "config.yaml")
	if err != nil {
		return err
	}
	config, err := render.RenderConfig(raw, s)
	if err != nil {
		return err
	}

	paths := envPaths(opts.Home)
	existing, found := render.LoadSecrets(paths)
	var rotate []string
	if found {
		if rotate, err = opts.UI.RotateSecrets(existingSecretList(existing)); err != nil {
			return err
		}
	}
	render.Fill(s, existing, rotate)
	env := &render.Env{Samples: samples}
	if samples != nil {
		if env.Extra, err = opts.UI.ExtraVars(askList(samples, env.OwnedKeys(s))); err != nil {
			return err
		}
	}

	override, err := (&render.Compose{
		ConfigPath: "../config/config.yaml",
		HostCerts:  opts.HostCerts,
		Mounts:     iacMounts(opts.Home, s),
	}).Render()
	if err != nil {
		return err
	}

	// Files generates onto s, so this prints the tokens a real run would write.
	if _, err := fmt.Fprintf(out, "dry run: no file would be written under %s\n\n", opts.Home.Root); err != nil {
		return err
	}
	stateYAML, err := state.Render(s)
	if err != nil {
		return err
	}
	if err := printSection(out, opts.Home.StateFile(), stateYAML); err != nil {
		return err
	}
	if err := printSection(out, opts.Home.ConfigYAML(), config); err != nil {
		return err
	}
	for _, path := range []string{paths.Core, paths.IAC, paths.Notifications} {
		if err := printSection(out, path, render.RenderEnvFile(env.Files(paths, s)[path])); err != nil {
			return err
		}
	}
	return printSection(out, opts.Home.ComposeOverride(), override)
}

// printSection prints one would-be file, its content indented so a multi-line
// file cannot be mistaken for the next path.
func printSection(w io.Writer, path string, content []byte) error {
	if _, err := fmt.Fprintf(w, "==> %s <==\n", path); err != nil {
		return err
	}
	for line := range strings.SplitSeq(strings.TrimRight(string(content), "\n"), "\n") {
		if _, err := fmt.Fprintf(w, "  %s\n", line); err != nil {
			return err
		}
	}
	return nil
}

// rel makes path relative to base for the compose -f arguments. Absolute would
// work too; relative keeps the command line readable.
func rel(base, path string) string {
	if r, err := filepath.Rel(base, path); err == nil {
		return r
	}
	return path
}

// askList flattens the samples' unanswered keys into the form's list. The label
// is the key itself: the wizard cannot know what an unknown key means.
func askList(samples *render.Samples, owned map[string]bool) []tui.Secret {
	var out []tui.Secret
	for _, s := range []*render.Sample{samples.Core, samples.IAC, samples.Notifications} {
		for _, v := range s.NeedsAsking(owned) {
			out = append(out, tui.Secret{Key: v.Key, Label: v.Key})
		}
	}
	return out
}

// warn writes a non-fatal warning to w.
func warn(w io.Writer, format string, args ...any) {
	if w != nil {
		fmt.Fprintf(w, "warning: "+format+"\n", args...)
	}
}

// fetchCompose downloads docker-compose.yml into src/ unless it is already
// there: an existing file may have been hand-edited.
func fetchCompose(ctx context.Context, dl *render.Download, dst string) error {
	if _, err := os.Stat(dst); err == nil {
		return nil
	} else if !os.IsNotExist(err) {
		return err
	}
	return dl.Save(ctx, "docker-compose.yml", dst)
}

// iacMounts are the cloud credential mounts, rebased on src/ — compose resolves
// relative paths against the first -f file's directory, the same base
// ConfigPath uses. Rebasing on h.Root instead lands every mount one directory
// too deep, and compose silently binds a path that does not hold the key.
func iacMounts(h home.Home, s *state.State) []render.Mount {
	var out []render.Mount
	for _, m := range render.IACMounts(s) {
		if r, err := filepath.Rel(h.SrcDir(), m.Source); err == nil {
			m.Source = r
		}
		out = append(out, m)
	}
	return out
}

// envPaths is where each env file lives under the managed home.
func envPaths(h home.Home) render.EnvPaths {
	return render.EnvPaths{
		Core:          h.CoreEnv(),
		IAC:           h.ServiceEnv("iac"),
		Notifications: h.ServiceEnv("notifications"),
	}
}

// existingSecretList names the secrets to offer for rotation. Only the
// generated ones: docker-compose.yml fixes the Postgres and RustFS values, so
// rotating those would only break the connection.
func existingSecretList(s state.Secrets) []tui.Secret {
	candidates := []struct {
		key, label, value string
	}{
		{"KUMOSS_IAC_TOKEN", "IaC service bearer token", s.IACToken},
		{"KUMOSS_NOTIFICATIONS_TOKEN", "Notifications service bearer token", s.NotificationsToken},
	}
	var out []tui.Secret
	for _, c := range candidates {
		if c.value != "" {
			out = append(out, tui.Secret{Key: c.key, Label: c.label})
		}
	}
	return out
}
