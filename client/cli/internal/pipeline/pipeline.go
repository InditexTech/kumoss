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
	"os"

	"github.com/InditexTech/kumoss/client/cli/internal/buildinfo"
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

	// 4. Collect answers. ModeKeep skips the forms and leaves the existing
	// env files untouched (Secrets are not in kumoss.yaml).
	if err := opts.UI.Configure(mode, s); err != nil {
		return err
	}

	// 5. Write the two YAML files. kumoss.yaml is skipped in ModeKeep: the
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

	// 6. Write the three env files. ModeKeep leaves them alone: they are the
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
		if err := (&render.Env{}).Write(paths, s); err != nil {
			return err
		}
	}

	// 7. Write compose.override.yml. Always regenerated: it is generated, not
	// user state, and it is what points core's config mount at the file written
	// above (the compose file's own ./config.yaml resolves to src/config.yaml).
	override := &render.Compose{
		Path:       opts.Home.ComposeOverride(),
		ConfigPath: "../config/config.yaml",
	}
	if err := override.Write(); err != nil {
		return err
	}

	// 8. Ask whether to start the stack. Docker pull/up come in the next slice;
	// the answers are collected and carried in s.
	if _, err := opts.UI.RunDocker(); err != nil {
		return err
	}

	return nil
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
// prompt. Only the generated ones are offered; mapping/authz stay empty unless
// the user set them by hand.
func existingSecretList(s state.Secrets) []tui.Secret {
	candidates := []struct {
		key, label, value string
	}{
		{"KUMOSS_IAC_TOKEN", "IaC service bearer token", s.IACToken},
		{"KUMOSS_NOTIFICATIONS_TOKEN", "Notifications service bearer token", s.NotificationsToken},
		{"KUMOSS_SQL_DATABASE_URL", "Postgres password (embedded in the database URL)", s.CoreDBPassword},
		{"RUSTFS_ACCESS_KEY", "RustFS access key", s.RustFSAccessKey},
		{"RUSTFS_SECRET_KEY", "RustFS secret key", s.RustFSSecretKey},
	}
	var out []tui.Secret
	for _, c := range candidates {
		if c.value != "" {
			out = append(out, tui.Secret{Key: c.key, Label: c.label})
		}
	}
	return out
}
