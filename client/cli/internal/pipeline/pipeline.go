// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package pipeline runs the `kumoss init` flow: prepare the home skeleton,
// fetch the compose stack, collect configuration, write the state, config and
// env files, and optionally pull and start the containers. It is a plain
// function so the steps run without Cobra, and every side effect (the terminal,
// the network, docker) goes through an injected seam the caller can stub.
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

	// PersistHome records the resolved root in the pointer file, so later
	// invocations find it without repeating --home. Set only when the user
	// passed --home explicitly.
	PersistHome bool
	UI          tui.UI

	// Download fetches the repo files (config.yaml, docker-compose.yml). nil
	// uses the real fetcher at the release tag; tests inject a stub so no
	// network is needed.
	Download *render.Download

	// Warn receives non-fatal warnings (the env samples could not be fetched).
	// nil discards them.
	Warn io.Writer

	// Docker starts the stack. nil builds the real `docker compose` runner;
	// tests inject a stub so no daemon is needed.
	Docker docker.Runner

	// Foreground keeps `docker compose up` attached: logs stream until Ctrl-C,
	// which also stops the stack. Useful when debugging a start-up. The default
	// is detached (`up -d`), which is what an installer wants. Set by the
	// --foreground flag.
	Foreground bool

	// HostCerts writes the corporate CA wiring into compose.override.yml, so core
	// and searxng trust the host's roots behind a TLS-inspecting proxy. Set by
	// the --host-certs flag; off by default, as the default root directory does
	// not exist on a normal network.
	HostCerts bool

	// DryRun prints the files the run would write to Out and writes nothing.
	// Set by the --dry-run flag.
	DryRun bool

	// Out receives the dry-run report. nil discards it.
	Out io.Writer
}

// RunPipeline executes the pipeline top to bottom. Every step is idempotent, so a
// failed run is fixed by running it again. ctx comes from the caller (Cobra's
// command context), so an interrupt aborts the network steps and a foreground
// `docker compose up`.
//
// With opts.DryRun nothing is written: no directory, no pointer, no file, no
// container. The same wizard runs and the files it would write are printed to
// opts.Out, so a run can be inspected without touching the install.
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

	// 2. Fetch the compose file into src/. Skipped when it already exists: it
	// may have been hand-edited, and every later step is idempotent anyway.
	if err := fetchCompose(ctx, dl, opts.Home.ComposeFile()); err != nil {
		return err
	}

	// 3. Detect an existing install. When kumoss.yaml is present, load it and
	// ask whether to reconfigure or keep it; otherwise start fresh.
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

	// 4. Fetch the env samples. They define which keys each env file carries,
	// so a failure is warned about, not fatal: the built-in key list still
	// produces a usable file set.
	samples, err := render.FetchSamples(ctx, dl)
	if err != nil {
		warn(opts.Warn, "could not fetch the env samples (%v); falling back to the built-in key list. Review the generated .env files against core/env.sample and services/*/env.sample in the repo, or the documentation.", err)
	}

	// 5. Collect answers. ModeKeep skips the forms and leaves the existing
	// env files untouched (Secrets are not in kumoss.yaml).
	if err := opts.UI.Configure(mode, s); err != nil {
		return err
	}

	// 6. Write the two YAML files. ModeKeep writes neither: it keeps every file
	// as-is, which is what "Keep it as is" promises.
	if mode != tui.ModeKeep {
		// The notifications service refuses to boot without a webhook, so an
		// enabled flag without one would break the stack on start. Downgrade
		// instead, with the one warning that says why.
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

	// 7. Write the three env files. ModeKeep leaves them alone: they are the
	// only copy of the secrets, so rewriting could rotate a running stack's
	// tokens. Otherwise, reuse what exists and offer to rotate any of it first.
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
		// Reuse what the files hold, minus anything the user chose to rotate;
		// Write generates fresh values for exactly those.
		render.Fill(s, existing, rotate)

		env := &render.Env{Samples: samples}
		if samples != nil {
			// Sample keys with no value and no wizard owner are the ones only
			// the user can supply (e.g. SLACK_WEBHOOK_URL).
			env.Extra, err = opts.UI.ExtraVars(askList(samples, env.OwnedKeys(s)))
			if err != nil {
				return err
			}
		}
		if err := env.Write(paths, s); err != nil {
			return err
		}
	}

	// 8. Write compose.override.yml. Regenerated unless the user kept the
	// install: it is generated, not user state, and it is what points core's
	// config mount at the file written above (the compose file's own
	// ./config.yaml resolves to src/config.yaml). An existing file is only
	// replaced with consent, since it may have been hand-edited; a fresh
	// install has nothing to ask about.
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
			}
			if err := override.Write(); err != nil {
				return err
			}
		}
	}

	// 9. Ask whether to start the stack, then pull what is missing and start it.
	// The recreate is what makes a reconfigure take effect: compose compares the
	// service definition, not the bytes of the mounted config.yaml or .env, so a
	// plain `up -d` would leave the old containers running with the old files.
	// Foreground replaces the detach, not the recreate.
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

// download returns the fetcher for the repo files: the injected one, or the real
// fetcher at the release tag.
func (o Options) download() *render.Download {
	if o.Download != nil {
		return o.Download
	}
	return &render.Download{Fetch: (&source.Fetcher{}).Fetch, Tag: buildinfo.KumossTag()}
}

// dryRun is RunPipeline with every write replaced by a report. It runs the same
// wizard on the same state, so the answers and the fetched defaults are
// identical to a real run; only the side effects differ. The state file is read
// when present, so an existing install previews a reconfigure.
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

	// The same gate as the real run, or the preview would show a stack that
	// cannot start.
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

	override, err := (&render.Compose{ConfigPath: "../config/config.yaml", HostCerts: opts.HostCerts}).Render()
	if err != nil {
		return err
	}

	// Secrets are generated onto s by Files, so print what was generated or the
	// preview would show the run's real tokens redacted to nothing.
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

// printSection prints one would-be file: its path, then its content indented so
// a multi-line file cannot be mistaken for the next path.
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

// rel makes path relative to base, for the compose -f arguments. compose is run
// with the home root as its working directory, so absolute paths would work too;
// relative ones keep the command line readable and the project name derived from
// the directory rather than overridden by it.
func rel(base, path string) string {
	if r, err := filepath.Rel(base, path); err == nil {
		return r
	}
	return path
}

// askList flattens the samples' unanswered keys into the form's list. The label
// is the key itself: the wizard does not know what an unknown sample key means.
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

// fetchCompose downloads docker-compose.yml into src/, unless it is already
// there. An existing file wins: it may have been hand-edited, and re-downloading
// would discard that.
func fetchCompose(ctx context.Context, dl *render.Download, dst string) error {
	if _, err := os.Stat(dst); err == nil {
		return nil
	} else if !os.IsNotExist(err) {
		return err
	}
	return dl.Save(ctx, "docker-compose.yml", dst)
}

// envPaths is where each env file lives under the managed home.
func envPaths(h home.Home) render.EnvPaths {
	return render.EnvPaths{
		Core:          h.CoreEnv(),
		IAC:           h.ServiceEnv("iac"),
		Notifications: h.ServiceEnv("notifications"),
	}
}

// existingSecretList names the secrets found in the env files, for the rotation
// prompt. Only the generated ones are offered: the Postgres password and the
// RustFS keys come from the sample because docker-compose.yml fixes them, so
// rotating them here would only break the connection.
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
