// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// repoDefault is a trimmed copy of the repo's config.yaml, with the keys the
// forms own and the keys they do not.
const repoDefault = `
environment: "development"
oidc:
  issuer_url: ""
  clock_skew_seconds: 60
orchestration:
  enable_compliance_checker: true
  max_drift_reports: 3
paths:
  upload_folder: "/workspaces"
  session_plan_filename: "session.plan"
llm:
  model: "vertex_ai/claude-sonnet-5-5"
  small_model: "vertex_ai/gemini-3.8-flash"
  temperature: 0.1
  max_output_tokens: 32000
  timeout: 600
storage:
  provider: "RUSTFS"
  bucket: "kumoss-artifacts"
  terraform_state_bucket: "kumoss-terraform-state"
  terraform_state_filename: "terraform.tfstate"
  endpoint_url: "http://object-storage:9000"
  public_endpoint_url: "http://localhost:9000"
  region: "us-east-1"
  connect_timeout: 3.0
  presign_expiry_seconds: 172800
git:
  provider: "GITHUB"
  author_name: "Kumoss"
  author_email: "kumoss@noreply.invalid"
`

func stubFetch(body string) func(context.Context, string, string) ([]byte, error) {
	return func(_ context.Context, _, path string) ([]byte, error) {
		if path != "config.yaml" {
			return nil, os.ErrNotExist
		}
		return []byte(body), nil
	}
}

// stubConfig builds a Config writing into dir/config, with the fetch stubbed.
func stubConfig(dir, body string) *Config {
	return &Config{
		Download: &Download{Fetch: stubFetch(body), Tag: "v1.0.0"},
		Path:     filepath.Join(dir, "config", "config.yaml"),
		Example:  filepath.Join(dir, "config", "config.yaml.example"),
	}
}

func TestRenderOverlaysAnswersAndKeepsTheRest(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config", "config.yaml")

	s := &state.State{
		LLM: state.LLM{
			Model:           "anthropic/claude-sonnet-5",
			SmallModel:      "anthropic/claude-haiku-4-5",
			Temperature:     0.2,
			MaxOutputTokens: 16000,
			Timeout:         300,
		},
		Git: state.Git{Provider: "GITLAB", AuthorName: "Bot", AuthorEmail: "bot@example.invalid"},
		Storage: state.Storage{
			Provider:             "S3",
			Bucket:               "my-artifacts",
			TerraformStateBucket: "", // repository-declared state
			Region:               "eu-west-1",
		},
	}

	c := stubConfig(dir, repoDefault)
	if err := c.Write(context.Background(), s); err != nil {
		t.Fatalf("Render: %v", err)
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	var doc map[string]any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("parse: %v", err)
	}

	// Overlaid: the answers win.
	llm := doc["llm"].(map[string]any)
	if llm["model"] != "anthropic/claude-sonnet-5" || llm["small_model"] != "anthropic/claude-haiku-4-5" {
		t.Errorf("llm not overlaid: %+v", llm)
	}
	if llm["max_output_tokens"] != 16000 {
		t.Errorf("max_output_tokens = %v, want 16000", llm["max_output_tokens"])
	}
	git := doc["git"].(map[string]any)
	if git["provider"] != "GITLAB" || git["author_email"] != "bot@example.invalid" {
		t.Errorf("git not overlaid: %+v", git)
	}

	// Storage: overlaid provider/bucket, empty terraform_state_bucket preserved
	// as an empty string (never a YAML null), and untouched keys kept.
	storage := doc["storage"].(map[string]any)
	if storage["provider"] != "S3" || storage["bucket"] != "my-artifacts" {
		t.Errorf("storage not overlaid: %+v", storage)
	}
	if v, ok := storage["terraform_state_bucket"]; !ok || v != "" {
		t.Errorf("terraform_state_bucket = %#v, want empty string present", storage["terraform_state_bucket"])
	}
	if storage["terraform_state_filename"] != "terraform.tfstate" {
		t.Errorf("untouched storage key lost: %+v", storage)
	}
	if storage["presign_expiry_seconds"] != 172800 {
		t.Errorf("untouched storage key lost: %+v", storage)
	}

	// Untouched top-level blocks survive.
	if doc["environment"] != "development" {
		t.Errorf("environment lost: %v", doc["environment"])
	}
	if _, ok := doc["orchestration"]; !ok {
		t.Error("orchestration block lost")
	}
	if _, ok := doc["paths"]; !ok {
		t.Error("paths block lost")
	}
	if _, ok := doc["oidc"]; !ok {
		t.Error("oidc block lost")
	}
}

func TestRenderKeepsTheExampleWithComments(t *testing.T) {
	dir := t.TempDir()

	// The repo default, with comments the generated file cannot keep.
	const withComments = "# the llm block\nllm:\n  model: \"vertex_ai/x\"  # complex tasks\n"
	c := stubConfig(dir, withComments)
	if err := c.Write(context.Background(), &state.State{}); err != nil {
		t.Fatalf("Render: %v", err)
	}

	example, err := os.ReadFile(c.Example)
	if err != nil {
		t.Fatalf("read example: %v", err)
	}
	if string(example) != withComments {
		t.Errorf("example not byte-identical to the fetched file:\n%s", example)
	}

	// The generated file has the answer and none of the comments.
	generated, _ := os.ReadFile(c.Path)
	if strings.Contains(string(generated), "#") {
		t.Errorf("generated config kept comments: %s", generated)
	}
}

func TestRenderFetchError(t *testing.T) {
	dir := t.TempDir()
	c := &Config{
		Download: &Download{Fetch: func(context.Context, string, string) ([]byte, error) {
			return nil, os.ErrNotExist
		}, Tag: "v1.0.0"},
		Path:    filepath.Join(dir, "config.yaml"),
		Example: filepath.Join(dir, "config.yaml.example"),
	}
	if err := c.Write(context.Background(), &state.State{}); err == nil {
		t.Fatal("Render accepted a failed fetch")
	}
}
