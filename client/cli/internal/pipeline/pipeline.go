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
	"gopkg.in/yaml.v3"
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
	out := opts.Out
	if out == nil {
		out = io.Discard
	}

	// Ensure the directory skeleton exists.
	if err := opts.Home.Ensure(); err != nil {
		return err
	}
	if opts.PersistHome {
		if err := home.SetPointer(opts.Home.Root); err != nil {
			return err
		}
	}

	dl := opts.download()

	// Fetch the compose file. Skipped if present: it may be hand-edited.
	if err := fetchCompose(ctx, dl, opts.Home.ComposeFile()); err != nil {
		return err
	}

	// An existing kumoss.yaml means asking whether to reconfigure or keep.
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

	// Fetch the env samples for their key sets. A failure warns rather than
	// stopping: the built-in list still produces a usable file set.
	samples, err := render.FetchSamples(ctx, dl)
	if err != nil {
		warn(opts.Warn, "could not fetch the env samples (%v); falling back to the built-in key list. Review the generated .env files against core/env.sample and services/*/env.sample in the repo, or the documentation.", err)
	}

	// The form shows what config.yaml holds, so a fresh install does not ask
	// for a value that already has one. A file that does not parse is not a
	// reason to stop: the fields just stay blank.
	opts.UI.SetDefaults(configDoc(opts.Home.ConfigYAML()))

	// Seed the secrets a form asks for from the files an earlier run wrote,
	// before the forms open. Fill below does this for the generated tokens,
	// but it runs after the wizard: the storage console keys are typed, so
	// their boxes would open on the container default and re-confirming one
	// would reset a key that was already changed.
	seedAskedSecrets(s, envPaths(opts.Home))

	// Collect answers. ModeKeep skips the forms entirely.
	if err := opts.UI.Configure(mode, s); err != nil {
		return err
	}

	// Write the two YAML files. ModeKeep writes neither, as promised.
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

	// Write the three env files. ModeKeep leaves them alone: they hold the
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
		render.FillCloud(s, paths)

		env := &render.Env{Samples: samples}
		if err := env.Write(paths, s); err != nil {
			return err
		}
	}

	// Write compose.override.yml, which is what points core's config mount
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
			override, err := renderCompose(opts.Home, s, opts.HostCerts)
			if err != nil {
				return err
			}
			if err := os.WriteFile(path, override, 0o644); err != nil {
				return err
			}
		}
		// The console block hands object-storage its own credential file, so
		// write it whenever the console is on — even if the override above was
		// kept, since a hand-edited override may still reference it.
		if s.Storage.ConsoleEnabled {
			if err := render.WriteObjectStorageEnv(opts.Home.ObjectStorageEnv(), s); err != nil {
				return err
			}
		}
		// Same for langfuse-web's key pair, which its override block names.
		if s.Secrets.LangfusePublicKey != "" {
			if err := render.WriteLangfuseEnv(opts.Home.LangfuseEnv(), s); err != nil {
				return err
			}
		}
	}

	// Pull and start. The recreate is what makes a reconfigure take effect:
	// compose compares the service definition, not the bytes of a mounted file,
	// so a plain `up -d` would keep the old containers and the old values.
	run, err := opts.UI.RunDocker()
	if err != nil {
		return err
	}
	if run {
		runner := opts.Docker
		if runner == nil {
			runner = docker.NewCompose(opts.Home)
		}
		if err := runner.Pull(ctx); err != nil {
			return fmt.Errorf("pull images: %w", err)
		}
		if err := runner.Up(ctx, mode != tui.ModeFresh, !opts.Foreground); err != nil {
			return fmt.Errorf("start the stack: %w", err)
		}
		// In the foreground the logs own the terminal until Ctrl-C, so there is
		// no moment to print the URLs.
		if !opts.Foreground {
			fmt.Fprint(out, stackURLs(s))
		}
	}

	return nil
}

// stackURLs are where a browser reaches the stack once `up` returns. Host
// paths, because the containers expose their ports only inside the compose
// network; the proxy publishes them.
//
// The S3 API on 9000 is not listed: it is what the core talks to, not
// something to open in a browser. The console is, when it is enabled.
//
// Langfuse replaced Phoenix as the monitoring UI. It listens on a port of its
// own, because the stock image bakes its base path in at build time, but the
// address printed here is the proxy's /langfuse, which redirects there: one
// origin to remember, and the port stays an implementation detail. The old
// /monitoring/ line pointed at a location nginx does not have, which fell
// through to the SPA's index.html.
func stackURLs(s *state.State) string {
	out := "Kumoss is up:\n  app            http://localhost/\n"
	if s.Storage.ConsoleEnabled {
		out += "  RustFS console http://localhost:9001/rustfs/console/\n"
	}
	return out + "  Langfuse       http://localhost/langfuse\n"
}

// seedAskedSecrets pre-fills the secrets the wizard asks for rather than
// generates, so their forms open on what is already installed.
func seedAskedSecrets(s *state.State, paths render.EnvPaths) {
	existing, found := render.LoadSecrets(paths)
	if !found {
		return
	}
	if s.Secrets.RustFSAccessKey == "" {
		s.Secrets.RustFSAccessKey = existing.RustFSAccessKey
	}
	if s.Secrets.RustFSSecretKey == "" {
		s.Secrets.RustFSSecretKey = existing.RustFSSecretKey
	}
}

// configDoc parses the installed config.yaml for the wizard's defaults, or nil
// when it is missing or unreadable.
func configDoc(path string) map[string]any {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return nil
	}
	return doc
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
	render.FillCloud(s, paths)
	env := &render.Env{Samples: samples}

	override, err := renderCompose(opts.Home, s, opts.HostCerts)
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
	if err := printSection(out, opts.Home.ComposeOverride(), override); err != nil {
		return err
	}
	if !s.Storage.ConsoleEnabled {
		return nil
	}
	return printSection(out, opts.Home.ObjectStorageEnv(),
		render.RenderEnvFile(render.ObjectStorageEnvVars(s)))
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

// renderCompose builds compose.override.yml for this home and state, for init
// to write and for config to diff. HostCerts is a separate answer the cloud
// forms never ask about.
func renderCompose(h home.Home, s *state.State, hostCerts bool) ([]byte, error) {
	return (&render.Compose{
		ConfigPath: "../config/config.yaml",
		HostCerts:  hostCerts,
		Mounts:     iacMounts(h, s),
		Console:    s.Storage.ConsoleEnabled,
		Langfuse:   s.Secrets.LangfusePublicKey != "",
	}).Render()
}

// envPaths is where each env file lives under the managed home.
func envPaths(h home.Home) render.EnvPaths {
	return render.EnvPaths{
		Core:          h.CoreEnv(),
		IAC:           h.ServiceEnv("iac"),
		Notifications: h.ServiceEnv("notifications"),
		Mapping:       h.ServiceEnv("mapping"),
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
