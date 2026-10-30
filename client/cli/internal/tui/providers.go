// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strings"

	"charm.land/huh/v2"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// credential is one secret the user types into a masked field. Name is the
// ENV-VAR NAME the value is written under (state.LLM.Credentials and friends
// are keyed by env-var name, not by provider). Title is what the form shows.
type credential struct {
	Name  string
	Title string
}

// llmProvider is a row of the provider Select. Prefix is the LiteLLM
// `<provider>/` string used to derive the model id; Credentials are the
// provider's default env vars (docs: reference/llm-providers). DefaultModel
// and DefaultSmallModel seed the model inputs.
//
// Freeform marks the "Other" row: the provider is not in this table, so the
// form asks for a credential name and value by hand instead of offering a
// fixed list.
type llmProvider struct {
	Name              string // select key, e.g. "Anthropic"
	Prefix            string // LiteLLM prefix, e.g. "anthropic"
	DefaultModel      string
	DefaultSmallModel string
	Credentials       []credential
	Freeform          bool
}

// otherProvider is the escape hatch for a LiteLLM provider not listed here. Its
// Prefix is empty; the user types the credential env-var name and value.
var otherProvider = llmProvider{Name: "Other (enter credentials manually)", Freeform: true}

// llmProviders mirrors the LiteLLM provider list in
// docs/src/modules/main/pages/reference/llm-providers.adoc. Only the default
// env var names are carried: model_list's custom `os.environ/...` names are an
// advanced escape hatch and stay hand-edited in config.yaml.
var llmProviders = []llmProvider{
	{
		Name: "Anthropic", Prefix: "anthropic",
		DefaultModel: "anthropic/claude-sonnet-5", DefaultSmallModel: "anthropic/claude-haiku-4-5",
		Credentials: []credential{{"ANTHROPIC_API_KEY", "Anthropic API key"}},
	},
	{
		Name: "Google Vertex AI", Prefix: "vertex_ai",
		DefaultModel: "vertex_ai/claude-sonnet-4-5", DefaultSmallModel: "vertex_ai/gemini-3.7-flash",
		Credentials: []credential{
			{"VERTEXAI_PROJECT", "Vertex AI project id"},
			{"VERTEXAI_LOCATION", "Vertex AI region (e.g. europe-west1)"},
			{"VERTEXAI_CREDENTIALS", "Service-account key JSON (blank = Application Default Credentials)"},
		},
	},
	{
		Name: "Google AI Studio", Prefix: "gemini",
		DefaultModel: "gemini/gemini-3.7-pro", DefaultSmallModel: "gemini/gemini-3.7-flash",
		Credentials: []credential{{"GEMINI_API_KEY", "Gemini API key"}},
	},
	{
		Name: "OpenAI", Prefix: "openai",
		DefaultModel: "openai/gpt-5", DefaultSmallModel: "openai/gpt-5-mini",
		Credentials: []credential{
			{"OPENAI_API_KEY", "OpenAI API key"},
			{"OPENAI_API_BASE", "API base (blank = https://api.openai.com/v1)"},
		},
	},
	{
		Name: "Azure OpenAI", Prefix: "azure",
		DefaultModel: "azure/your-deployment", DefaultSmallModel: "azure/your-small-deployment",
		Credentials: []credential{
			{"AZURE_API_KEY", "Azure API key"},
			{"AZURE_API_BASE", "Resource endpoint (https://<resource>.openai.azure.com)"},
			{"AZURE_API_VERSION", "API version"},
		},
	},
	{
		Name: "Azure AI Foundry", Prefix: "azure_ai",
		DefaultModel: "azure_ai/claude-sonnet-4-5", DefaultSmallModel: "azure_ai/claude-haiku-4-5",
		Credentials: []credential{
			{"AZURE_AI_API_KEY", "Azure AI API key"},
			{"AZURE_AI_API_BASE", "Azure AI endpoint"},
		},
	},
	{
		Name: "AWS Bedrock", Prefix: "bedrock",
		DefaultModel: "bedrock/anthropic.claude-sonnet-4-5", DefaultSmallModel: "bedrock/anthropic.claude-haiku-4-5",
		Credentials: []credential{
			{"AWS_ACCESS_KEY_ID", "AWS access key id"},
			{"AWS_SECRET_ACCESS_KEY", "AWS secret access key"},
			{"AWS_REGION_NAME", "AWS region"},
		},
	},
	{
		Name: "Ollama (self-hosted)", Prefix: "ollama",
		DefaultModel: "ollama/llama3.3", DefaultSmallModel: "ollama/llama3.3",
		Credentials: []credential{{"OLLAMA_API_BASE", "Ollama base URL (not localhost inside the compose network)"}},
	},
	{
		Name: "vLLM (OpenAI-compatible, self-hosted)", Prefix: "hosted_vllm",
		DefaultModel: "hosted_vllm/your-model", DefaultSmallModel: "hosted_vllm/your-small-model",
		Credentials: []credential{
			{"HOSTED_VLLM_API_BASE", "vLLM server base URL (http://<host>:<port>)"},
			{"HOSTED_VLLM_API_KEY", "API key (blank if the server needs none)"},
		},
	},
	{
		Name: "OpenAI-compatible (LM Studio, LocalAI…)", Prefix: "openai",
		DefaultModel: "openai/your-model", DefaultSmallModel: "openai/your-small-model",
		Credentials: []credential{
			{"OPENAI_API_KEY", "API key (use a placeholder such as `none` if the server ignores it)"},
			{"OPENAI_API_BASE", "Server base URL (http://<host>:<port>/v1)"},
		},
	},
}

// llmProviderByName returns the provider row for a stored llm.model prefix, or
// nil when the prefix is unknown (hand-edited config). Reconfigure uses it to
// preselect the provider row and to name the credential fields.
func llmProviderByName(prefix string) *llmProvider {
	for i := range llmProviders {
		if llmProviders[i].Prefix == prefix {
			return &llmProviders[i]
		}
	}
	return nil
}

// llmProviderOptions is the Select's option list: every known provider plus the
// free-text "Other" row. The value is the row's index into allProviders.
func llmProviderOptions() []huh.Option[int] {
	opts := make([]huh.Option[int], 0, len(llmProviders)+1)
	for i, p := range llmProviders {
		opts = append(opts, huh.NewOption(p.Name, i))
	}
	opts = append(opts, huh.NewOption(otherProvider.Name, -1))
	return opts
}

// providerAt returns the row for a Select index, or the Other row for -1.
func providerAt(idx int) llmProvider {
	if idx < 0 || idx >= len(llmProviders) {
		return otherProvider
	}
	return llmProviders[idx]
}

// providerIndex returns the Select index preselecting the row matching prefix,
// or the Other index (-1) when the prefix is unknown.
func providerIndex(prefix string) int {
	for i := range llmProviders {
		if llmProviders[i].Prefix == prefix {
			return i
		}
	}
	return -1
}

// prefixOf returns the `<provider>/` part of a LiteLLM model string, or "".
func prefixOf(model string) string {
	if i := strings.IndexByte(model, '/'); i > 0 {
		return model[:i]
	}
	return ""
}

// storageModel is a row of the Storage model Select. It is the CLI
// discriminator (state.Storage.Model) that drives config.yaml's
// storage.provider and whether terraform_state_bucket is empty.
type storageModel struct {
	Name        string // select key
	Model       string // state.Storage.Model
	Provider    string // → storage.provider enum
	Managed     bool   // false = repository-declared state (empty terraform_state_bucket)
	Region      bool   // whether the region field is relevant
	Credentials []credential
}

var storageModels = []storageModel{
	{
		Name: "Bundled RustFS", Model: "bundled", Provider: "RUSTFS", Managed: true,
		// Keys are generated into core/.env, not typed: they must match the
		// object-storage container's own credentials.
	},
	{
		Name: "External S3-compatible", Model: "external_s3", Provider: "S3", Managed: true, Region: true,
		// Blank credentials: a static key defeats boto3's default chain.
		Credentials: nil,
	},
	{
		Name: "Azure Storage Account", Model: "external_azure", Provider: "STORAGE_ACCOUNT", Managed: true,
		Credentials: []credential{{"STORAGE_ACCOUNT_KEY", "Storage account shared key"}},
	},
	{
		Name: "Repository-declared state", Model: "repository", Provider: "S3", Managed: false, Region: true,
		// Backend credentials go to services/iac/.env, not core/.env.
		Credentials: nil,
	},
}

func storageModelByName(model string) *storageModel {
	for i := range storageModels {
		if storageModels[i].Model == model {
			return &storageModels[i]
		}
	}
	return nil
}

// cloud is one row of the Cloud MultiSelect. Field holds the form group that
// collects its credentials, added by cloudForms.
type cloud struct {
	Name string
	Key  string
}

var clouds = []cloud{
	{Name: "AWS", Key: "aws"},
	{Name: "Azure", Key: "azure"},
	{Name: "Google Cloud", Key: "gcp"},
	{Name: "Oracle Cloud", Key: "oci"},
	{Name: "Kubernetes", Key: "kubernetes"},
}

// selected reports whether key is in the picked clouds.
func selected(picked []string, key string) bool {
	for _, p := range picked {
		if p == key {
			return true
		}
	}
	return false
}

// cloudPicked reports whether a cloud's credentials are already stored, so a
// reconfigure run opens with that cloud preselected.
func cloudPicked(s *state.State, key string) bool {
	switch key {
	case "aws":
		return s.Cloud.AWS != nil
	case "azure":
		return s.Cloud.Azure != nil
	case "gcp":
		return s.Cloud.GCP != nil
	case "oci":
		return s.Cloud.OCI != nil
	case "kubernetes":
		return s.Cloud.Kubernetes != nil
	}
	return false
}

// ensureCloud returns the Cloud sub-struct for a cloud key, allocating it on
// first use so the renderer only sees the clouds the user picked.
func ensureCloud(s *state.State, key string) any {
	switch key {
	case "aws":
		if s.Cloud.AWS == nil {
			s.Cloud.AWS = &state.AWSAuth{Method: "static"}
		}
		return s.Cloud.AWS
	case "azure":
		if s.Cloud.Azure == nil {
			s.Cloud.Azure = &state.AzureAuth{}
		}
		return s.Cloud.Azure
	case "gcp":
		if s.Cloud.GCP == nil {
			s.Cloud.GCP = &state.GCPAuth{}
		}
		return s.Cloud.GCP
	case "oci":
		if s.Cloud.OCI == nil {
			s.Cloud.OCI = &state.OCIAuth{}
		}
		return s.Cloud.OCI
	case "kubernetes":
		if s.Cloud.Kubernetes == nil {
			s.Cloud.Kubernetes = &state.KubernetesAuth{}
		}
		return s.Cloud.Kubernetes
	}
	return nil
}
