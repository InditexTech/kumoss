// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package pipeline runs the `kumoss init` flow: prepare the home skeleton,
// fetch the compose stack, collect configuration, write the state, config and
// env files, and start the containers. It is a plain function so the steps are
// testable without a terminal and reusable outside the Cobra command.
package pipeline

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
	"github.com/InditexTech/kumoss/client/cli/internal/docker"
	"github.com/InditexTech/kumoss/client/cli/internal/home"
	"github.com/InditexTech/kumoss/client/cli/internal/render"
	"github.com/InditexTech/kumoss/client/cli/internal/source"
	"github.com/InditexTech/kumoss/client/cli/internal/state"
	"github.com/InditexTech/kumoss/client/cli/internal/tui"
)

// Options is the resolved input to Run.
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
}

// RunPipeline executes the pipeline top to bottom. Every step is idempotent, so a
// failed run is fixed by running it again. ctx comes from the caller (Cobra's
// command context), so an interrupt aborts the network steps.
func RunPipeline(ctx context.Context, opts Options) error {
	// 1. Ensure the directory skeleton exists.
	if err := opts.Home.Ensure(); err != nil {
		return err
	}
	if opts.PersistHome {
		if err := home.SetPointer(opts.Home.Root); err != nil {
			return err
		}
	}

	dl := opts.Download
	if dl == nil {
		dl = &render.Download{Fetch: (&source.Fetcher{}).Fetch, Tag: buildinfo.KumossTag()}
	}

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

	// 6. Write the two YAML files. kumoss.yaml is skipped in ModeKeep: the
	// stored values did not change. config.yaml is always regenerated, which is
	// the only config file ModeKeep produces.
	if mode != tui.ModeKeep {
		if err := state.Save(opts.Home.StateFile(), s); err != nil {
			return err
		}
	}
	cfg := &render.Config{
		Download: dl,
		Path:     opts.Home.ConfigYAML(),
		Example:  opts.Home.ConfigExample(),
	}
	if err := cfg.Write(ctx, s); err != nil {
		return err
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

	// 8. Write compose.override.yml. Always regenerated: it is generated, not
	// user state, and it is what points core's config mount at the file written
	// above (the compose file's own ./config.yaml resolves to src/config.yaml).
	override := &render.Compose{
		Path:       opts.Home.ComposeOverride(),
		ConfigPath: "../config/config.yaml",
	}
	if err := override.Write(); err != nil {
		return err
	}

	// 9. Ask whether to start the stack, then pull what is missing and start it.
	// The recreate is what makes a reconfigure take effect: compose compares the
	// service definition, not the bytes of the mounted config.yaml or .env, so a
	// plain `up -d` would leave the old containers running with the old files.
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
		if _, err := runner.Pull(ctx); err != nil {
			return fmt.Errorf("pull images: %w", err)
		}
		if err := runner.Up(ctx, mode != tui.ModeFresh); err != nil {
			return fmt.Errorf("start the stack: %w", err)
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
