// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strings"

	"charm.land/huh/v2"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// credential is one masked field. Name is the ENV-VAR NAME it is written
// under — the credential maps are keyed by variable, not by provider.
type credential struct {
	Name  string
	Title string
}

// llmProvider is a row of the provider Select: the LiteLLM prefix, the
// provider's default env vars, and seeds for the two model inputs.
//
// Freeform marks the "Other" row, where the form asks for credential names by
// hand instead of offering a fixed list.
type llmProvider struct {
	Name              string // select key, e.g. "Anthropic"
	Prefix            string // LiteLLM prefix, e.g. "anthropic"
	DefaultModel      string
	DefaultSmallModel string
	Credentials       []credential
	Freeform          bool
}

// otherProvider is the escape hatch for a provider not listed here.
var otherProvider = llmProvider{Name: "Other (enter credentials manually)", Freeform: true}

// llmProviders mirrors docs/.../reference/llm-providers.adoc. Only the default
// env var names: model_list's custom `os.environ/...` names stay hand-edited.
//
// The model ids are seeds for a new install, not a claim about what is newest.
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
			{"OPENAI_API_BASE", "API base; blank means the default https://api.openai.com/v1. Point it at your server for LM Studio/LocalAI."},
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
			{"OPENAI_API_BASE", "Server base URL, e.g. http://<host>:<port>/v1. Reconfiguring an openai/ model reopens this as OpenAI; the same variable."},
		},
	},
}

// llmProviderOptions values are indexes into llmProviders; -1 is "Other".
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

// providerIndex preselects the row matching prefix, or -1 when unknown. Two
// rows share the openai prefix and the first wins: they write the same
// OPENAI_* variables, only the hint text differs.
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

// storageModel is the CLI discriminator driving storage.provider and whether
// terraform_state_bucket is empty.
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
		// Keys are generated, not typed: they must match the container's own.
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

// cloud is one row of the Cloud MultiSelect; Key selects the state.Cloud
// field, for cloudPicked, ensureCloud and cloudStep's commit.
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

// cloudPicked preselects a cloud whose credentials are already stored.
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

// ensureCloud allocates a cloud's struct on first use.
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
