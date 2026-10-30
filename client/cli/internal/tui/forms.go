// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strconv"
	"strings"

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

// Configure runs the interactive forms and fills s. In ModeReconfigure s
// arrives pre-filled from kumoss.yaml and the forms open on those values; in
// ModeFresh s is zero-valued and the forms open empty. ModeKeep never reaches
// here. Secrets collected by the forms live in the yaml:"-" maps on s, so they
// reach the .env files and never kumoss.yaml.
func (w *Wizard) Configure(mode Mode, s *state.State) error {
	if mode == ModeKeep {
		return nil
	}

	// The LLM step is split in two because the credential fields depend on the
	// provider chosen in the first form. Pick the provider, then build the
	// details form from that choice.
	idx, err := w.llmProviderStep(s)
	if err != nil {
		return err
	}
	if err := w.llmDetailsStep(s, providerAt(idx)); err != nil {
		return err
	}

	steps := []func(*state.State) (*huh.Form, func()){
		w.gitStep,
		w.storageStep,
		w.cloudStep,
		w.engineStep,
	}
	for _, step := range steps {
		form, commit := step(s)
		if err := w.run(form); err != nil {
			return err
		}
		commit()
	}
	return nil
}

// RotateSecrets offers the secrets already in the env files and returns the keys
// to regenerate. Multi-select: nothing selected keeps every secret, which is the
// safe default for a running stack. Rotating a token breaks any client still
// presenting the old one, so the description says so.
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
				Description("Select any to regenerate. Leave all unselected to keep the running stack working.").
				Options(opts...).
				Value(&rotate),
		),
	)
	if err := w.run(form); err != nil {
		return nil, err
	}
	return rotate, nil
}

// RunDocker asks whether to pull and start the stack now.
func (w *Wizard) RunDocker() (bool, error) {
	run := true
	form := huh.NewForm(
		huh.NewGroup(
			huh.NewConfirm().
				Title("Start the Kumoss stack now?").
				Description("Yes pulls the images and runs `docker compose up -d`.").
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

// llmProviderStep asks which provider serves the models and returns its row
// index (into llmProviders, or -1 for the free-text "Other" row). Preselected
// from the stored model prefix on reconfigure.
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

// llmDetailsStep collects the two models, the tuning knobs, and the chosen
// provider's credentials. For the free-text "Other" provider it asks for a
// credential name and value by hand.
func (w *Wizard) llmDetailsStep(s *state.State, provider llmProvider) error {
	s.LLM.Provider = provider.Prefix
	if s.LLM.Model == "" {
		s.LLM.Model = provider.DefaultModel
	}
	if s.LLM.SmallModel == "" {
		s.LLM.SmallModel = provider.DefaultSmallModel
	}
	if s.LLM.Temperature == 0 {
		s.LLM.Temperature = 0.1
	}
	if s.LLM.MaxOutputTokens == 0 {
		s.LLM.MaxOutputTokens = 32000
	}
	if s.LLM.Timeout == 0 {
		s.LLM.Timeout = 600
	}
	if s.LLM.Credentials == nil {
		s.LLM.Credentials = map[string]string{}
	}

	// huh binds *string, so each numeric knob and credential gets a local;
	// commit parses the locals back into the struct once the form has run.
	temp := strconv.FormatFloat(s.LLM.Temperature, 'g', -1, 64)
	maxTokens := strconv.Itoa(s.LLM.MaxOutputTokens)
	timeout := strconv.FormatFloat(s.LLM.Timeout, 'g', -1, 64)
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
			Description("Completion cap per call (default 32000).").
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
	s.LLM.Temperature, _ = strconv.ParseFloat(temp, 64)
	s.LLM.MaxOutputTokens, _ = strconv.Atoi(maxTokens)
	s.LLM.Timeout, _ = strconv.ParseFloat(timeout, 64)
	for i, c := range provider.Credentials {
		s.LLM.Credentials[c.Name] = values[i]
	}
	// The free-text provider collects an arbitrary number of credentials in a
	// loop after the fixed form, since huh cannot add fields mid-run.
	if provider.Freeform {
		return w.collectFreeformCredentials(s)
	}
	return nil
}

// collectFreeformCredentials asks for credential name/value pairs until the
// user leaves the name blank. Each round is its own form; a blank name ends the
// loop. The last value entered for a repeated name wins.
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

// cloudStep picks the clouds this deployment serves and opens one credential
// group per pick. Unpicked clouds stay hidden and their structs stay nil.
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
				Description("Which clouds your Terraform modules target. Skip if none.").
				Options(cloudOptions()...).
				Value(&picked),
		).Title("Clouds"),
	}
	for _, c := range clouds {
		groups = append(groups, cloudGroup(s, c, &picked))
	}
	// ensureCloud allocates every cloud's struct so its fields can be bound;
	// drop the ones the user did not pick so the renderer only sees the picked
	// clouds.
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
	return huh.NewForm(groups...), commit
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
				Value(&s.Engine.BUSLAcknowledged),
		).WithHideFunc(func() bool { return s.Engine.Binary != "terraform" }),
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
		huh.NewInput().Title("Subscription id").
			Description("ARM_SUBSCRIPTION_ID (overwritten per request by the scope)").Value(&a.SubscriptionID),
	).Title("Azure")
}

func gcpGroup(s *state.State) *huh.Group {
	a := ensureCloud(s, "gcp").(*state.GCPAuth)
	return huh.NewGroup(
		huh.NewInput().
			Title("Service-account key file path").
			Description("GOOGLE_APPLICATION_CREDENTIALS. Host path, mounted read-only into the iac container.").
			Value(&a.KeyFile),
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
