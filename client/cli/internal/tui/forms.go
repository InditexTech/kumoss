// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strconv"
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/huh/v2"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// SelectStateAction asks what to do with an existing kumoss.yaml.
func (w *Wizard) SelectStateAction() (Mode, error) {
	mode := ModeFresh
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[Mode]().
				Title("There is an existing kumoss.yaml state file. Choose an action").
				Options(
					huh.NewOption("Reconfigure", ModeReconfigure),
					huh.NewOption("Keep it as is and continue", ModeKeep),
				).
				Value(&mode),
		),
	)
	if err := w.run(form); err != nil {
		return ModeFresh, err
	}
	return mode, nil
}

// Configure runs the forms and fills s: pre-filled in ModeReconfigure, empty
// in ModeFresh, never called for ModeKeep. Credentials land in the yaml:"-"
// maps, so they reach the .env files and never kumoss.yaml.
func (w *Wizard) Configure(mode Mode, s *state.State) error {
	if mode == ModeKeep {
		return nil
	}

	if err := w.LLM(s); err != nil {
		return err
	}
	for _, step := range []func(*state.State) error{w.Git, w.State, w.Cloud, w.Engine, w.Notifications} {
		if err := step(s); err != nil {
			return err
		}
	}
	return nil
}

// multiSelectKeyMap renames the toggle help to "space". huh labels it "x",
// hiding the obvious key on a list of checkboxes. Both stay bound.
func multiSelectKeyMap() *huh.KeyMap {
	km := huh.NewDefaultKeyMap()
	km.MultiSelect.Toggle = key.NewBinding(
		key.WithKeys("space", "x"),
		key.WithHelp("space", "toggle"),
	)
	return km
}

// RotateSecrets returns the keys to regenerate. Selecting nothing keeps every
// secret, the safe default: rotating breaks any client holding the old one.
func (w *Wizard) RotateSecrets(found []Secret) ([]string, error) {
	opts := make([]huh.Option[string], len(found))
	for i, s := range found {
		opts[i] = huh.NewOption(s.Label+" ("+s.Key+")", s.Key)
	}
	var rotate []string
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewMultiSelect[string]().
				Title("Secrets already present in the env files").
				Description("Space (or x) toggles a secret, enter confirms. Select any to regenerate; leave all unselected to keep the running stack working.").
				Options(opts...).
				// One line per secret, plus title, description and help bar.
				Height(len(opts) + 5).
				Value(&rotate),
		),
	).WithKeyMap(multiSelectKeyMap())
	if err := w.run(form); err != nil {
		return nil, err
	}
	return rotate, nil
}

// ExtraVars asks for the sample keys the wizard does not own. Blank answers
// are allowed: an empty var is how the stack says "not configured".
func (w *Wizard) ExtraVars(keys []Secret) (map[string]string, error) {
	// huh binds to addresses, so collect into a slice and zip back by index.
	answers := make([]string, len(keys))
	fields := make([]huh.Field, len(keys))
	for i, k := range keys {
		fields[i] = huh.NewInput().
			Title(k.Label).
			Description(k.Key).
			EchoMode(huh.EchoModePassword).
			Value(&answers[i])
	}
	if err := w.run(huh.NewForm(huh.NewGroup(fields...).Title("Additional settings"))); err != nil {
		return nil, err
	}
	values := make(map[string]string, len(keys))
	for i, k := range keys {
		values[k.Key] = answers[i]
	}
	return values, nil
}

// ConfirmRegenerate defaults to no: losing a hand-edited file is silent.
func (w *Wizard) ConfirmRegenerate(what string) (bool, error) {
	regenerate := false
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewConfirm().
				Title(what + " already exists. Regenerate it?").
				Description("Regenerating discards any manual edits to the file.").
				Affirmative("Regenerate").
				Negative("Keep it").
				Value(&regenerate),
		),
	)
	if err := w.run(form); err != nil {
		return false, err
	}
	return regenerate, nil
}

// RunDocker asks whether to start now; the pipeline picks detached or not.
func (w *Wizard) RunDocker() (bool, error) {
	run := true
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewConfirm().
				Title("Start the Kumoss stack now?").
				Description("Yes pulls the missing images and starts the stack: `docker compose up -d`, or in the foreground with --foreground.").
				Affirmative("Start it").
				Negative("Not now").
				Value(&run),
		),
	)
	if err := w.run(form); err != nil {
		return false, err
	}
	return run, nil
}

// llmProviderStep returns the chosen row index, or -1 for "Other".
// Preselected from the stored model prefix on reconfigure.
func (w *Wizard) llmProviderStep(s *state.State) (int, error) {
	prefix := s.LLM.Provider
	if prefix == "" {
		prefix = prefixOf(s.LLM.Model)
	}
	idx := providerIndex(prefix)

	form := huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[int]().
				Title("LLM provider").
				Description("Determines the credential variables the core reads at boot.").
				Options(llmProviderOptions()...).
				Value(&idx),
		).Title("LLM provider"),
	)
	if err := w.run(form); err != nil {
		return 0, err
	}
	return idx, nil
}

// llmDetailsStep collects the models, the knobs and the provider's
// credentials — or asks for name/value pairs by hand for "Other".
func (w *Wizard) llmDetailsStep(s *state.State, provider llmProvider) error {
	s.LLM.Provider = provider.Prefix
	if s.LLM.Model == "" {
		s.LLM.Model = provider.DefaultModel
	}
	if s.LLM.SmallModel == "" {
		s.LLM.SmallModel = provider.DefaultSmallModel
	}
	// The knobs have no default here: nil leaves the fetched config.yaml value
	// in place (render.overlay), so the repo stays the source of truth.
	if s.LLM.Credentials == nil {
		s.LLM.Credentials = map[string]string{}
	}

	// huh binds *string, so each knob and credential gets a local that commit
	// parses back once the form has run. An unset knob shows blank: pre-filling
	// 0 claimed an answer the user never gave.
	temp := knobFloat(s.LLM.Temperature)
	maxTokens := knobInt(s.LLM.MaxOutputTokens)
	timeout := knobFloat(s.LLM.Timeout)
	values := make([]string, len(provider.Credentials))
	fields := []huh.Field{
		huh.NewInput().
			Title("Complex-tasks model").
			Description(modelHint(provider) + " — code generation, planning.").
			Value(&s.LLM.Model).
			Validate(required),
		huh.NewInput().
			Title("Cheap-filler model").
			Description(modelHint(provider) + " — filtering, summaries, status.").
			Value(&s.LLM.SmallModel).
			Validate(required),
	}
	for i, c := range provider.Credentials {
		values[i] = s.LLM.Credentials[c.Name]
		fields = append(fields, huh.NewInput().
			Title(c.Title).
			Description(c.Name).
			EchoMode(huh.EchoModePassword).
			Value(&values[i]))
	}
	fields = append(fields,
		huh.NewInput().
			Title("Temperature").
			Description("0–1, sent with every chat completion (default 0.1).").
			Value(&temp).
			Validate(floatRange(0, 1)),
		huh.NewInput().
			Title("Max output tokens").
			Description("Completion cap per call (default 64000).").
			Value(&maxTokens).
			Validate(intMin(1)),
		huh.NewInput().
			Title("Timeout (seconds)").
			Description("Per inference call, before retries (default 600).").
			Value(&timeout).
			Validate(floatMin(0)),
	)

	form := huh.NewForm(huh.NewGroup(fields...).Title("LLM — " + provider.Name))
	if err := w.run(form); err != nil {
		return err
	}
	s.LLM.Temperature = parseKnobFloat(temp)
	s.LLM.MaxOutputTokens = parseKnobInt(maxTokens)
	s.LLM.Timeout = parseKnobFloat(timeout)
	for i, c := range provider.Credentials {
		s.LLM.Credentials[c.Name] = values[i]
	}
	// Looped after the fixed form, since huh cannot add fields mid-run.
	if provider.Freeform {
		return w.collectFreeformCredentials(s)
	}
	return nil
}

// collectFreeformCredentials loops one form per pair until the name is left
// blank. The last value for a repeated name wins.
func (w *Wizard) collectFreeformCredentials(s *state.State) error {
	for {
		name := ""
		nameForm := huh.NewForm(
			huh.NewGroup(
				huh.NewInput().
					Title("Credential env-var name").
					Description("e.g. MY_PROVIDER_API_KEY. Leave blank to finish.").
					Value(&name),
			).Title("Credentials"),
		)
		if err := w.run(nameForm); err != nil {
			return err
		}
		if strings.TrimSpace(name) == "" {
			return nil
		}

		value := ""
		valueForm := huh.NewForm(
			huh.NewGroup(
				huh.NewInput().
					Title("Value for " + name).
					EchoMode(huh.EchoModePassword).
					Value(&value),
			).Title("Credentials"),
		)
		if err := w.run(valueForm); err != nil {
			return err
		}
		s.LLM.Credentials[name] = value
	}
}

// modelHint is the description prefix for the two model fields.
func modelHint(provider llmProvider) string {
	if provider.Prefix == "" {
		return "LiteLLM string provider/model-id"
	}
	return "LiteLLM string " + provider.Prefix + "/<model-id>"
}

// gitStep collects the push provider, author identity, and credentials.
func (w *Wizard) gitStep(s *state.State) (*huh.Form, func()) {
	if s.Git.Provider == "" {
		s.Git.Provider = "GITHUB"
	}
	if s.Git.AuthorName == "" {
		s.Git.AuthorName = "Kumoss"
	}
	if s.Git.AuthorEmail == "" {
		s.Git.AuthorEmail = "kumoss@noreply.invalid"
	}
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Git provider").
				Description("Host the core pushes branches to and opens pull requests on.").
				Options(
					huh.NewOption("GitHub", "GITHUB"),
					huh.NewOption("Azure DevOps", "AZURE_DEVOPS"),
					huh.NewOption("GitLab", "GITLAB"),
				).
				Value(&s.Git.Provider),
			huh.NewInput().
				Title("Commit author name").
				Value(&s.Git.AuthorName).
				Validate(required),
			huh.NewInput().
				Title("Commit author email").
				Value(&s.Git.AuthorEmail).
				Validate(email),
			huh.NewInput().
				Title("Git username").
				Description("GIT_USER. Blank skips credential setup.").
				Value(&s.Git.User),
			huh.NewInput().
				Title("Git token").
				Description("GIT_TOKEN. Personal access token for push and pull requests.").
				EchoMode(huh.EchoModePassword).
				Value(&s.Git.Token),
		).Title("Git"),
	)
	return form, func() {}
}

// storageStep collects the storage model and its settings.
func (w *Wizard) storageStep(s *state.State) (*huh.Form, func()) {
	model := pickStorage(s)
	s.Storage.Provider = model.Provider
	if s.Storage.Bucket == "" {
		s.Storage.Bucket = "kumoss-artifacts"
	}
	// Managed state owns the bucket; repository-declared state leaves it "".
	if !model.Managed {
		s.Storage.TerraformStateBucket = ""
	} else if s.Storage.TerraformStateBucket == "" {
		s.Storage.TerraformStateBucket = "kumoss-terraform-state"
	}
	if s.Storage.Credentials == nil {
		s.Storage.Credentials = map[string]string{}
	}

	values := make([]string, len(model.Credentials))
	fields := []huh.Field{
		huh.NewInput().
			Title("Artifacts bucket").
			Description("Generated reports, plans and code changes.").
			Value(&s.Storage.Bucket).
			Validate(required),
	}
	if model.Managed {
		fields = append(fields, huh.NewInput().
			Title("Terraform state bucket").
			Description("Blank = each repository declares its own backend.").
			Value(&s.Storage.TerraformStateBucket))
	}
	if model.Region {
		fields = append(fields, huh.NewInput().
			Title("Region").
			Description("Ignored by Azure Storage Account.").
			Value(&s.Storage.Region))
	}
	fields = append(fields,
		huh.NewInput().
			Title("Endpoint URL").
			Description("In-cluster address of the store.").
			Value(&s.Storage.EndpointURL),
		huh.NewInput().
			Title("Public endpoint URL").
			Description("Browser-facing address used to sign download links.").
			Value(&s.Storage.PublicEndpointURL),
	)
	for i, c := range model.Credentials {
		values[i] = s.Storage.Credentials[c.Name]
		fields = append(fields, huh.NewInput().
			Title(c.Title).
			Description(c.Name).
			EchoMode(huh.EchoModePassword).
			Value(&values[i]))
	}

	form := huh.NewForm(huh.NewGroup(fields...).Title("Storage — " + model.Name))
	commit := func() {
		for i, c := range model.Credentials {
			s.Storage.Credentials[c.Name] = values[i]
		}
	}
	return form, commit
}

// cloudStep opens one credential group per picked cloud; the rest stay hidden
// and their structs stay nil.
func (w *Wizard) cloudStep(s *state.State) (*huh.Form, func()) {
	picked := []string{}
	for _, c := range clouds {
		if cloudPicked(s, c.Key) {
			picked = append(picked, c.Key)
		}
	}

	groups := []*huh.Group{
		huh.NewGroup(
			huh.NewMultiSelect[string]().
				Title("Cloud providers").
				Description("Which clouds your Terraform modules target? Space (or x) toggles a cloud, enter confirms. Skip if none.").
				Options(cloudOptions()...).
				// One line per cloud, plus title, description and help bar.
				Height(len(clouds) + 5).
				Value(&picked),
		).Title("Clouds"),
	}
	for _, c := range clouds {
		groups = append(groups, cloudGroup(s, c, &picked))
	}
	// ensureCloud allocated every struct so the fields could be bound; drop
	// the unpicked ones so the renderer sees only real answers.
	commit := func() {
		if !selected(picked, "aws") {
			s.Cloud.AWS = nil
		}
		if !selected(picked, "azure") {
			s.Cloud.Azure = nil
		}
		if !selected(picked, "gcp") {
			s.Cloud.GCP = nil
		}
		if !selected(picked, "oci") {
			s.Cloud.OCI = nil
		}
		if !selected(picked, "kubernetes") {
			s.Cloud.Kubernetes = nil
		}
	}
	return huh.NewForm(groups...).WithKeyMap(multiSelectKeyMap()), commit
}

// engineStep selects the IaC engine and, for Terraform, gates on its license.
func (w *Wizard) engineStep(s *state.State) (*huh.Form, func()) {
	if s.Engine.Binary == "" {
		s.Engine.Binary = "tofu"
	}
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("IaC engine").
				Description("IAC_BINARY. The bundled image ships both engines.").
				Options(
					huh.NewOption("OpenTofu (MPL-2.0)", "tofu"),
					huh.NewOption("Terraform (BUSL-1.1)", "terraform"),
				).
				Value(&s.Engine.Binary),
		).Title("IaC engine"),
		huh.NewGroup(
			huh.NewConfirm().
				Title("Acknowledge the Terraform license").
				Description("Terraform is under BUSL-1.1. Confirm your use complies with its terms.").
				Affirmative("I acknowledge").
				Negative("Cancel").
				Value(&s.Engine.BUSLAcknowledged).
				Validate(acknowledgeTerraform),
		).WithHideFunc(func() bool { return s.Engine.Binary != "terraform" }),
	)
	return form, func() {}
}

// notificationsStep asks both questions in one form: the service refuses to
// start without a webhook, so enabled and the URL must not disagree.
func (w *Wizard) notificationsStep(s *state.State) (*huh.Form, func()) {
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewConfirm().
				Title("Send Slack notifications?").
				Description("services.notifications.enabled. Off leaves the notifications service idle; the core answers 503 on its endpoint.").
				Affirmative("Yes").
				Negative("No").
				Value(&s.Notifications.Enabled),
			huh.NewInput().
				Title("Slack webhook URL").
				Description("SLACK_WEBHOOK_URL. Required to enable: anyone holding it can post to the channel.").
				EchoMode(huh.EchoModePassword).
				Value(&s.Notifications.SlackWebhookURL).
				// Only when enabling, or "No" would still demand a webhook.
				Validate(func(v string) error {
					if s.Notifications.Enabled {
						return required(v)
					}
					return nil
				}),
		).Title("Notifications"),
	)
	return form, func() {}
}

func cloudOptions() []huh.Option[string] {
	opts := make([]huh.Option[string], len(clouds))
	for i, c := range clouds {
		opts[i] = huh.NewOption(c.Name, c.Key)
	}
	return opts
}

// cloudGroup builds the credential group for one cloud, hidden unless picked.
func cloudGroup(s *state.State, c cloud, picked *[]string) *huh.Group {
	var g *huh.Group
	switch c.Key {
	case "aws":
		g = awsGroup(s)
	case "azure":
		g = azureGroup(s)
	case "gcp":
		g = gcpGroup(s)
	case "oci":
		g = ociGroup(s)
	case "kubernetes":
		g = kubernetesGroup(s)
	}
	return g.WithHideFunc(func() bool { return !selected(*picked, c.Key) })
}

func awsGroup(s *state.State) *huh.Group {
	a := ensureCloud(s, "aws").(*state.AWSAuth)
	return huh.NewGroup(
		huh.NewSelect[string]().
			Title("AWS authentication").
			Options(
				huh.NewOption("Static access keys", "static"),
				huh.NewOption("Named profile", "profile"),
			).
			Value(&a.Method),
		huh.NewInput().
			Title("Access key id").
			Description("AWS_ACCESS_KEY_ID").
			EchoMode(huh.EchoModePassword).
			Value(&a.AccessKey),
		huh.NewInput().
			Title("Secret access key").
			Description("AWS_SECRET_ACCESS_KEY").
			EchoMode(huh.EchoModePassword).
			Value(&a.SecretKey),
		huh.NewInput().
			Title("Region").
			Description("AWS_REGION. Required.").
			Value(&a.Region),
		huh.NewInput().
			Title("Profile name").
			Description("AWS_PROFILE. For the named-profile method; mounts ~/.aws read-only.").
			Value(&a.Profile),
	).Title("AWS")
}

func azureGroup(s *state.State) *huh.Group {
	a := ensureCloud(s, "azure").(*state.AzureAuth)
	return huh.NewGroup(
		huh.NewInput().Title("Tenant id").Description("ARM_TENANT_ID").Value(&a.TenantID),
		huh.NewInput().Title("Client id").Description("ARM_CLIENT_ID").Value(&a.ClientID),
		huh.NewInput().Title("Client secret").Description("ARM_CLIENT_SECRET").
			EchoMode(huh.EchoModePassword).Value(&a.ClientSecret),
	).Title("Azure")
}

func gcpGroup(s *state.State) *huh.Group {
	a := ensureCloud(s, "gcp").(*state.GCPAuth)
	if a.Method == "" {
		a.Method = "json"
	}
	return huh.NewGroup(
		huh.NewSelect[string]().
			Title("Google Cloud credentials").
			Description("Inline JSON needs no file mount; a key file is mounted read-only into the iac container.").
			Options(
				huh.NewOption("Service-account JSON (paste it)", "json"),
				huh.NewOption("Service-account key file path", "file"),
			).
			Value(&a.Method),
		huh.NewText().
			Title("Service-account JSON").
			Description("GOOGLE_CREDENTIALS. The whole key, pasted. It stays in services/iac/.env, never in kumoss.yaml.").
			Value(&a.InlineJSON).
			Validate(func(v string) error {
				if a.Method == "json" {
					return required(v)
				}
				return nil
			}),
		huh.NewInput().
			Title("Service-account key file path").
			Description("GOOGLE_APPLICATION_CREDENTIALS. Host path, mounted read-only into the iac container.").
			Value(&a.KeyFile).
			Validate(func(v string) error {
				if a.Method == "file" {
					return required(v)
				}
				return nil
			}),
	).Title("Google Cloud")
}

func ociGroup(s *state.State) *huh.Group {
	a := ensureCloud(s, "oci").(*state.OCIAuth)
	return huh.NewGroup(
		huh.NewInput().
			Title("OCI config file path").
			Description("OCI_CONFIG_FILE. Host path, mounted read-only into the iac container.").
			Value(&a.ConfigPath),
	).Title("Oracle Cloud")
}

func kubernetesGroup(s *state.State) *huh.Group {
	a := ensureCloud(s, "kubernetes").(*state.KubernetesAuth)
	return huh.NewGroup(
		huh.NewInput().
			Title("Kubeconfig path").
			Description("KUBE_CONFIG_PATH. Host path, mounted read-only into the iac container.").
			Value(&a.KubeconfigPath),
	).Title("Kubernetes")
}

// pickStorage preselects the storage model row from the stored discriminator.
func pickStorage(s *state.State) *storageModel {
	if m := storageModelByName(s.Storage.Model); m != nil {
		return m
	}
	return &storageModels[0]
}

// The optional LLM knobs are pointers so "unanswered" and "zero" stay apart:
// nil keeps the repo's value. These four convert to and from the form's input.

func knobFloat(v *float64) string {
	if v == nil {
		return ""
	}
	return strconv.FormatFloat(*v, 'g', -1, 64)
}

func knobInt(v *int) string {
	if v == nil {
		return ""
	}
	return strconv.Itoa(*v)
}

// parseKnobFloat returns nil for a blank box, and for junk Validate already
// refused — only reachable when the form was cancelled.
func parseKnobFloat(s string) *float64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil
	}
	return &f
}

func parseKnobInt(s string) *int {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return nil
	}
	return &n
}
