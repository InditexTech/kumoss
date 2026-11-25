// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
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

	return w.runSequence(s, w.allSteps())
}

// allSteps is every section's forms as one flat list, in the order the wizard
// asks them. Flat, not a sequence per section: the back keys walk this list, so
// leaving the first form of a section has to land on the last form of the one
// before it, not on the first form of its own section.
func (w *Wizard) allSteps() []step {
	var all []step
	for _, section := range [][]step{
		w.llmSteps(),
		w.gitSteps(),
		w.stateSteps(),
		w.cloudSteps(),
		w.engineSteps(),
		w.notifySteps(),
	} {
		all = append(all, section...)
	}
	return all
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

// providerLimit is the most providers a setup can name: the complex and the
// cheap model, one vendor each.
const providerLimit = 2

// llmPreselect maps stored prefixes back to select rows. "Other" has an empty
// prefix and is the -1 row, so it must be carried through rather than dropped:
// walking back to this form and forward again would otherwise lose the pick.
func llmPreselect(prefixes []string) []int {
	var picked []int
	for _, prefix := range prefixes {
		picked = append(picked, providerIndex(prefix))
	}
	return picked
}

// llmProviderStep writes the chosen rows into s.LLM.Providers as prefixes, in
// option-list order — huh returns multi-select values in list order, not press
// order, so llmRoleStep decides which of two leads. One provider covers both
// model roles; two let the complex and the cheap model come from different
// vendors. Preselected from the stored prefixes on reconfigure.
func (w *Wizard) llmProviderStep(s *state.State) error {
	picked := llmPreselect(s.LLM.Providers)

	form := newStepForm(
		newStepGroup(
			huh.NewMultiSelect[int]().
				Title("LLM providers").
				Description("Pick one, or two to use a different vendor for the complex and the cheap model. Space (or x) toggles, enter confirms.").
				Options(llmProviderOptions()...).
				// One line per provider, plus title, description and help bar.
				Height(len(llmProviders) + 6).
				Limit(providerLimit).
				Value(&picked),
		).Title("LLM provider"),
	)
	err := w.execStep(form)
	// Kept on a back too, so stepping away to fix an earlier answer does not
	// revert the pick. The rows are kept beside the prefixes: two rows share
	// the "openai" prefix, so only the row says which one was picked.
	if err == nil || errors.Is(err, errBack) {
		w.llmPicked = picked
		s.LLM.Providers = prefixesOf(picked)
	}
	if err != nil {
		return err
	}
	if len(picked) == 0 {
		return errors.New("pick at least one LLM provider")
	}
	return nil
}

// prefixesOf turns picked select rows into the prefixes state stores.
func prefixesOf(picked []int) []string {
	prefixes := make([]string, 0, len(picked))
	for _, idx := range picked {
		prefixes = append(prefixes, providerAt(idx).Prefix)
	}
	return prefixes
}

// llmRoleStep reorders s.LLM.Providers so index 0 is the provider serving the
// complex-tasks model; the other serves the cheap one. Preselected from the
// stored model so a reconfigure keeps the same split. Skipped unless exactly
// two providers were picked: with one, any order is role order.
func (w *Wizard) llmRoleStep(s *state.State) error {
	if len(s.LLM.Providers) != providerLimit {
		return errSkip
	}
	providers := w.llmProvidersOf(s)
	idx := 0
	// A stored model matching neither pick leaves the list order alone, which
	// is the same default a fresh run gets.
	// An empty prefix must not count: with no stored model prefixOf is "",
	// which would match the Other row's empty prefix and preselect it.
	if complexPrefix := prefixOf(s.LLM.Model); complexPrefix != "" && complexPrefix == providers[1].Prefix {
		idx = 1
	}
	form := newStepForm(
		newStepGroup(
			huh.NewSelect[int]().
				Title("Complex-tasks provider").
				Description("Serves llm.model; the other serves llm.small_model.").
				Options(
					huh.NewOption(providers[0].Name, 0),
					huh.NewOption(providers[1].Name, 1),
				).
				Value(&idx),
		).Title("LLM model roles"),
	)
	err := w.execStep(form)
	if err == nil || errors.Is(err, errBack) {
		if idx == 1 {
			s.LLM.Providers[0], s.LLM.Providers[1] = s.LLM.Providers[1], s.LLM.Providers[0]
			if len(w.llmPicked) == providerLimit {
				w.llmPicked[0], w.llmPicked[1] = w.llmPicked[1], w.llmPicked[0]
			}
		}
	}
	return err
}

// llmProviderAt resolves slot i to its provider row. The row the user picked
// is authoritative; the stored prefix is the fallback for a reconfigure that
// has not reopened the provider form yet, where it is all there is.
func (w *Wizard) llmProviderAt(s *state.State, i int) llmProvider {
	if i < len(w.llmPicked) {
		return providerAt(w.llmPicked[i])
	}
	return providerAt(providerIndex(s.LLM.Providers[i]))
}

// llmProvidersOf resolves every picked slot to its provider row.
func (w *Wizard) llmProvidersOf(s *state.State) []llmProvider {
	providers := make([]llmProvider, 0, len(s.LLM.Providers))
	for i := range s.LLM.Providers {
		providers = append(providers, w.llmProviderAt(s, i))
	}
	return providers
}

// llmProviderSlot asks slot i's models and credentials. Slot 0 serves the
// complex role and slot 1 the cheap one; a single provider fills both. The
// slot count is fixed so the step list never changes length, and a slot
// nobody picked skips itself.
func (w *Wizard) llmProviderSlot(i int) step {
	return func(s *state.State) error {
		if i >= len(s.LLM.Providers) {
			return errSkip
		}
		if s.LLM.Credentials == nil {
			s.LLM.Credentials = map[string]string{}
		}
		provider := w.llmProviderAt(s, i)
		return w.llmProviderForm(s, provider, i == 0, len(s.LLM.Providers))
	}
}

// llmFreeformSlot asks slot i's hand-entered credential pairs. It sits next to
// its own provider rather than at the end, so the order matches the single
// inline prompt it replaces.
func (w *Wizard) llmFreeformSlot(i int) step {
	return func(s *state.State) error {
		if i >= len(s.LLM.Providers) {
			return errSkip
		}
		if !w.llmProviderAt(s, i).Freeform {
			return errSkip
		}
		if s.LLM.Credentials == nil {
			s.LLM.Credentials = map[string]string{}
		}
		return w.collectFreeformCredentials(s)
	}
}

// llmSteps is the LLM section: seven slots, fixed in number, each skipping
// itself when the answers so far do not call for it. A fixed list is what lets
// the wizard walk backwards into the section and land on the last form that
// actually applies.
func (w *Wizard) llmSteps() []step {
	return []step{
		w.llmProviderStep,
		w.llmRoleStep,
		w.llmKnobsStep,
		w.llmProviderSlot(0),
		w.llmFreeformSlot(0),
		w.llmProviderSlot(1),
		w.llmFreeformSlot(1),
	}
}

// llmKnobsStep asks the three settings both models share.
func (w *Wizard) llmKnobsStep(s *state.State) error {
	seed := llmDefaults(w.Doc)
	// huh binds *string, so each knob gets a local that commit parses back once
	// the form has run. A value neither the state nor the file set stays blank:
	// pre-filling 0 would claim an answer nobody gave.
	temp := firstNonEmpty(knobFloat(s.LLM.Temperature), seed.temperature)
	maxTokens := firstNonEmpty(knobInt(s.LLM.MaxOutputTokens), seed.maxTokens)
	timeout := firstNonEmpty(knobFloat(s.LLM.Timeout), seed.timeout)
	form := newStepForm(newStepGroup(
		huh.NewInput().
			Title(titled("Temperature", false)).
			Description("0–1, sent with every chat completion (default 0.1).").
			Value(&temp).
			Validate(floatRange(0, 1)),
		huh.NewInput().
			Title(titled("Max output tokens", false)).
			Description("Completion cap per call (default 64000).").
			Value(&maxTokens).
			Validate(intMin(1)),
		huh.NewInput().
			Title(titled("Timeout (seconds)", false)).
			Description("Per inference call, before retries (default 600).").
			Value(&timeout).
			Validate(floatMin(0)),
	).Title("LLM settings"))
	err := w.execStep(form)
	if err == nil || errors.Is(err, errBack) {
		s.LLM.Temperature = parseKnobFloat(temp)
		s.LLM.MaxOutputTokens = parseKnobInt(maxTokens)
		s.LLM.Timeout = parseKnobFloat(timeout)
	}
	return err
}

// llmProviderForm asks one provider's models and credentials. complex is true
// for the provider serving the complex role; count is how many were picked, so a
// lone provider is asked for both of its models.
func (w *Wizard) llmProviderForm(s *state.State, provider llmProvider, complex bool, count int) error {
	seed := llmDefaults(w.Doc)
	// Two providers: the first serves the complex role, the second the cheap
	// one. One provider fills both, so its second model comes from the same row.
	var model, small string
	if complex {
		model = modelFor(s.LLM.Model, seed.model, provider.DefaultModel, provider.Prefix)
	}
	if !complex || count == 1 {
		small = modelFor(s.LLM.SmallModel, seed.small, provider.DefaultSmallModel, provider.Prefix)
	}

	values := make([]string, len(provider.Credentials))
	fields := []huh.Field{}
	if complex {
		fields = append(fields, huh.NewInput().
			Title(titled("Complex-tasks model", false)).
			Description(modelHint(provider)+" — code generation, planning.").
			Value(&model).
			Validate(required))
	}
	// A provider picked alone fills both roles, so it is asked for both models.
	if !complex || count == 1 {
		title, hint := "Cheap-filler model", " — filtering, summaries, status."
		if complex {
			title = "Complex and cheap-filler models"
			hint = " — the same provider serves both."
		}
		fields = append(fields, huh.NewInput().
			Title(titled(title, false)).
			Description(modelHint(provider)+hint).
			Value(&small).
			Validate(required))
	}
	for i, c := range provider.Credentials {
		values[i] = s.LLM.Credentials[c.Name]
		optional := optionalCredentials[c.Name]
		field := huh.NewInput().
			Title(titled(c.Title, optional)).
			Description(c.Name).
			Value(&values[i])
		if c.Secret {
			field.EchoMode(huh.EchoModePassword)
		}
		// A blank key is a stack that cannot call the model: block it here
		// rather than at `kumoss run`. Only the optional ones may stay empty.
		if !optional {
			field.Validate(required)
		}
		fields = append(fields, field)
	}
	form := newStepForm(newStepGroup(fields...).Title("LLM — " + provider.Name))
	err := w.execStep(form)
	// Also on a back: these are locals seeded from the state, so an API key
	// typed here survives stepping away to fix an earlier answer. A freeform
	// provider's hand-entered pairs are their own slot, right after this one.
	if err == nil || errors.Is(err, errBack) {
		if complex {
			s.LLM.Model = model
		}
		if !complex || count == 1 {
			s.LLM.SmallModel = small
		}
		for i, c := range provider.Credentials {
			s.LLM.Credentials[c.Name] = values[i]
		}
	}
	return err
}

// modelFor picks what to show in a model box: the stored answer, else what
// config.yaml holds, else this provider's default — but only a candidate this
// provider actually serves. Dropping a provider leaves its model behind in the
// state, and offering that as the survivor's answer writes a stack that cannot
// call it: nothing would ask for the absent provider's key, and preflight
// would pass. A freeform provider has no prefix to check against, so anything
// stored for it stands.
func modelFor(stored, seeded, fallback, prefix string) string {
	for _, candidate := range []string{stored, seeded} {
		if candidate != "" && (prefix == "" || prefixOf(candidate) == prefix) {
			return candidate
		}
	}
	return fallback
}

// collectFreeformCredentials loops one form per pair until the name is left
// blank. The last value for a repeated name wins.
//
// The loop has no fixed length, so it cannot be a list of steps. Back out of
// the value form and the name form reopens; back out of the name form and the
// loop either hands the request up — when nothing has been entered, so the
// sequence reopens this provider's credential form — or finishes forward,
// keeping the pairs already given.
func (w *Wizard) collectFreeformCredentials(s *state.State) error {
	pairs := 0
	for {
		name := ""
		nameForm := newStepForm(
			newStepGroup(
				huh.NewInput().
					Title("Credential env-var name").
					Description("e.g. MY_PROVIDER_API_KEY. Leave blank to finish.").
					Value(&name),
			).Title("Credentials"),
		)
		if err := w.execStep(nameForm); err != nil {
			if errors.Is(err, errBack) {
				if pairs == 0 {
					return errBack
				}
				return nil
			}
			return err
		}
		if strings.TrimSpace(name) == "" {
			return nil
		}

		value := ""
		valueForm := newStepForm(
			newStepGroup(
				huh.NewInput().
					Title(titled("Value for "+name, false)).
					EchoMode(huh.EchoModePassword).
					Value(&value).
					Validate(required),
			).Title("Credentials"),
		)
		if err := w.execStep(valueForm); err != nil {
			if errors.Is(err, errBack) {
				// Reopen the name form; this pair is not committed.
				continue
			}
			return err
		}
		s.LLM.Credentials[name] = value
		pairs++
	}
}

// optionalTitle marks a field a blank answer is a supported setup for;
// requiredTitle is for the rest, so the form never leaves it to guesswork.
const (
	requiredTitle = " (required)"
	optionalTitle = " (optional)"
)

// titled appends the marker the title needs.
func titled(title string, optional bool) string {
	if optional {
		return title + optionalTitle
	}
	return title + requiredTitle
}

// modelHint is the description prefix for the two model fields.
func modelHint(provider llmProvider) string {
	if provider.Prefix == "" {
		return "LiteLLM string provider/model-id"
	}
	return "LiteLLM string " + provider.Prefix + "/<model-id>"
}

// gitStep collects the push provider, author identity, and credentials.
func (w *Wizard) gitStep(s *state.State) (*stepForm, func()) {
	if s.Git.Provider == "" {
		s.Git.Provider = "GITHUB"
	}
	if s.Git.AuthorName == "" {
		s.Git.AuthorName = "Kumoss"
	}
	if s.Git.AuthorEmail == "" {
		s.Git.AuthorEmail = "kumoss@noreply.invalid"
	}
	form := newStepForm(
		newStepGroup(
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
				Title(titled("Git username", true)).
				Description("GIT_USER. Blank skips credential setup.").
				Value(&s.Git.User),
			huh.NewInput().
				Title(titled("Git token", true)).
				Description("GIT_TOKEN. Personal access token for push and pull requests.").
				EchoMode(huh.EchoModePassword).
				Value(&s.Git.Token),
		).Title("Git"),
	)
	return form, func() {}
}

// storageModelStep picks the storage model. It is its own form because the
// fields below depend on it: a model picked in the same form would leave the
// credential and region fields of the previous one on screen.
func (w *Wizard) storageModelStep(s *state.State) error {
	model := pickStorage(s)
	picked := model.Model
	form := newStepForm(
		newStepGroup(
			huh.NewSelect[string]().
				Title("Storage model").
				Description("Where artifacts and, optionally, Terraform state are kept.").
				Options(storageModelOptions()...).
				Value(&picked),
		).Title("Storage"),
	)
	err := w.execStep(form)
	// Picked before the next step reads it, so its fields follow this choice.
	// Kept on a back too, or stepping away to fix an earlier answer would
	// quietly revert the model.
	if err == nil || errors.Is(err, errBack) {
		s.Storage.Model = picked
	}
	return err
}

// storageStep collects the storage model's settings.
func (w *Wizard) storageStep(s *state.State) (*stepForm, func()) {
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
	// The bundled container's addresses are known, so they are seeded rather
	// than asked; an external store has none to guess.
	if s.Storage.EndpointURL == "" {
		s.Storage.EndpointURL = model.EndpointURL
	}
	if s.Storage.PublicEndpointURL == "" {
		s.Storage.PublicEndpointURL = model.PublicEndpointURL
	}

	values := make([]string, len(model.Credentials))
	fields := []huh.Field{
		huh.NewInput().
			Title(titled("Artifacts bucket", false)).
			Description("Generated reports, plans and code changes.").
			Value(&s.Storage.Bucket).
			Validate(required),
	}
	if model.Managed {
		fields = append(fields, huh.NewInput().
			Title(titled("Terraform state bucket", true)).
			Description("Blank = each repository declares its own backend.").
			Value(&s.Storage.TerraformStateBucket))
	}
	if model.Region {
		fields = append(fields, huh.NewInput().
			Title(titled("Region", false)).
			Description("Ignored by Azure Storage Account.").
			Value(&s.Storage.Region).
			Validate(required))
	}
	fields = append(fields,
		huh.NewInput().
			Title(titled("Endpoint URL", false)).
			Description(storageDescriptions()[0]).
			Value(&s.Storage.EndpointURL).
			Validate(required),
		huh.NewInput().
			Title(titled("Public endpoint URL", false)).
			Description(storageDescriptions()[1]).
			Value(&s.Storage.PublicEndpointURL).
			Validate(required),
	)
	for i, c := range model.Credentials {
		values[i] = s.Storage.Credentials[c.Name]
		field := huh.NewInput().
			Title(titled(c.Title, false)).
			Description(c.Name).
			Value(&values[i]).
			Validate(required)
		if c.Secret {
			field.EchoMode(huh.EchoModePassword)
		}
		fields = append(fields, field)
	}

	form := newStepForm(newStepGroup(fields...).Title("Storage — " + model.Name))
	commit := func() {
		for i, c := range model.Credentials {
			s.Storage.Credentials[c.Name] = values[i]
		}
	}
	return form, commit
}

// cloudStep opens one credential group per picked cloud; the rest stay hidden
// and their structs stay nil.
func (w *Wizard) cloudStep(s *state.State) (*stepForm, func()) {
	picked := []string{}
	for _, c := range clouds {
		if cloudPicked(s, c.Key) {
			picked = append(picked, c.Key)
		}
	}

	groups := []*stepGroup{
		newStepGroup(
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
	return newStepForm(groups...), commit
}

// engineStep selects the IaC engine and, for Terraform, gates on its license.
func (w *Wizard) engineStep(s *state.State) (*stepForm, func()) {
	if s.Engine.Binary == "" {
		s.Engine.Binary = "tofu"
	}
	form := newStepForm(
		newStepGroup(
			huh.NewSelect[string]().
				Title("IaC engine").
				Description("IAC_BINARY. The bundled image ships both engines.").
				Options(
					huh.NewOption("OpenTofu (MPL-2.0)", "tofu"),
					huh.NewOption("Terraform (BUSL-1.1)", "terraform"),
				).
				Value(&s.Engine.Binary),
		).Title("IaC engine"),
		newStepGroup(
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
// start without a webhook, so enabled and the URL must not disagree. The webhook
// is its own group, hidden until the answer is Yes: huh hides groups, not
// fields, and a visible empty URL reads as a second question to answer.
func (w *Wizard) notificationsStep(s *state.State) (*stepForm, func()) {
	form := newStepForm(
		newStepGroup(
			huh.NewConfirm().
				Title("Send Slack notifications?").
				Description("services.notifications.enabled. Off leaves the notifications service idle; the core answers 503 on its endpoint.").
				Affirmative("Yes").
				Negative("No").
				Value(&s.Notifications.Enabled),
		).Title("Notifications"),
		newStepGroup(
			huh.NewInput().
				Title(titled("Slack webhook URL", false)).
				Description("SLACK_WEBHOOK_URL. Anyone holding it can post to the channel.").
				EchoMode(huh.EchoModePassword).
				Value(&s.Notifications.SlackWebhookURL).
				// Only when enabling, or "No" would still demand a webhook.
				Validate(func(v string) error {
					if s.Notifications.Enabled {
						return required(v)
					}
					return nil
				}),
		).WithHideFunc(func() bool { return notificationsWebhookHidden(s) }),
	)
	return form, func() {}
}

// notificationsWebhookHidden is the rule the form uses, kept callable so a test
// checks it without a terminal.
func notificationsWebhookHidden(s *state.State) bool { return !s.Notifications.Enabled }

func cloudOptions() []huh.Option[string] {
	opts := make([]huh.Option[string], len(clouds))
	for i, c := range clouds {
		opts[i] = huh.NewOption(c.Name, c.Key)
	}
	return opts
}

// cloudGroup builds the credential group for one cloud, hidden unless picked.
func cloudGroup(s *state.State, c cloud, picked *[]string) *stepGroup {
	var g *stepGroup
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

func awsGroup(s *state.State) *stepGroup {
	a := ensureCloud(s, "aws").(*state.AWSAuth)
	return newStepGroup(
		huh.NewSelect[string]().
			Title("AWS authentication").
			Options(
				huh.NewOption("Static access keys", "static"),
				huh.NewOption("Named profile", "profile"),
			).
			Value(&a.Method),
		huh.NewInput().
			Title(titled("Access key id", false)).
			Description("AWS_ACCESS_KEY_ID").
			EchoMode(huh.EchoModePassword).
			Value(&a.AccessKey),
		huh.NewInput().
			Title(titled("Secret access key", false)).
			Description("AWS_SECRET_ACCESS_KEY").
			EchoMode(huh.EchoModePassword).
			Value(&a.SecretKey),
		huh.NewInput().
			Title(titled("Region", false)).
			Description("AWS_REGION. Required.").
			Value(&a.Region),
		huh.NewInput().
			Title(titled("Profile name", true)).
			Description("AWS_PROFILE. For the named-profile method; mounts ~/.aws read-only.").
			Value(&a.Profile),
	).Title("AWS")
}

func azureGroup(s *state.State) *stepGroup {
	a := ensureCloud(s, "azure").(*state.AzureAuth)
	return newStepGroup(
		huh.NewInput().Title(titled("Tenant id", false)).Description("ARM_TENANT_ID").Value(&a.TenantID),
		huh.NewInput().Title(titled("Client id", false)).Description("ARM_CLIENT_ID").Value(&a.ClientID),
		huh.NewInput().Title(titled("Client secret", false)).Description("ARM_CLIENT_SECRET").
			EchoMode(huh.EchoModePassword).Value(&a.ClientSecret),
	).Title("Azure")
}

func gcpGroup(s *state.State) *stepGroup {
	a := ensureCloud(s, "gcp").(*state.GCPAuth)
	if a.Method == "" {
		a.Method = "json"
	}
	return newStepGroup(
		huh.NewSelect[string]().
			Title("Google Cloud credentials").
			Description("Inline JSON needs no file mount; a key file is mounted read-only into the iac container.").
			Options(
				huh.NewOption("Service-account JSON (paste it)", "json"),
				huh.NewOption("Service-account key file path", "file"),
			).
			Value(&a.Method),
		huh.NewText().
			Title(titled("Service-account JSON", false)).
			Description("GOOGLE_CREDENTIALS. The whole key, pasted. It stays in services/iac/.env, never in kumoss.yaml.").
			Value(&a.InlineJSON).
			Validate(func(v string) error {
				if a.Method == "json" {
					return jsonKey(v)
				}
				return nil
			}),
		huh.NewInput().
			Title(titled("Service-account key file path", false)).
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

func ociGroup(s *state.State) *stepGroup {
	a := ensureCloud(s, "oci").(*state.OCIAuth)
	return newStepGroup(
		huh.NewInput().
			Title(titled("OCI config file path", false)).
			Description("OCI_CONFIG_FILE. Host path, mounted read-only into the iac container.").
			Value(&a.ConfigPath),
	).Title("Oracle Cloud")
}

func kubernetesGroup(s *state.State) *stepGroup {
	a := ensureCloud(s, "kubernetes").(*state.KubernetesAuth)
	return newStepGroup(
		huh.NewInput().
			Title(titled("Kubeconfig path", false)).
			Description("KUBE_CONFIG_PATH. Host path, mounted read-only into the iac container.").
			Value(&a.KubeconfigPath),
	).Title("Kubernetes")
}

// storageDescriptions are the two endpoint hints, kept together so the form and
// its test read the same words. The first is where the core writes, the second
// what a browser downloads from: the same store, reached two ways.
func storageDescriptions() [2]string {
	return [2]string{
		"In-cluster address the core writes to, e.g. http://object-storage:9000. Use a host address only if the core can reach it.",
		"Browser-facing address of the same store, e.g. http://localhost:9000 through the proxy. Download links are signed against it, so it must serve the same bucket.",
	}
}

// pickStorage preselects the storage model row from the stored discriminator.
func pickStorage(s *state.State) *storageModel {
	if m := storageModelByName(s.Storage.Model); m != nil {
		return m
	}
	return &storageModels[0]
}

// storageModelOptions is the storage select, one row per model.
func storageModelOptions() []huh.Option[string] {
	opts := make([]huh.Option[string], 0, len(storageModels))
	for _, m := range storageModels {
		opts = append(opts, huh.NewOption(m.Name, m.Model))
	}
	return opts
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
