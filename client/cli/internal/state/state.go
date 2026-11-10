// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

// State is kumoss.yaml: the answers that survive a run. Secrets, the cloud and
// engine structs and every credential map are yaml:"-" and never reach it.
type State struct {
	SchemaVersion int           `yaml:"schema_version" json:"schema_version"`
	LLM           LLM           `yaml:"llm"            json:"llm"`
	Git           Git           `yaml:"git"            json:"git"`
	Cloud         Cloud         `yaml:"-"              json:"-"`
	Engine        Engine        `yaml:"-"              json:"-"`
	Storage       Storage       `yaml:"storage"        json:"storage"`
	Notifications Notifications `yaml:"notifications"  json:"notifications"`
	Secrets       Secrets       `yaml:"-"              json:"-"`
}

type LLM struct {
	Provider string `yaml:"-" json:"-"` // Wizard-only: which provider row was picked. Used to derive the model-id prefix and the credential variable names. Re-derived from llm.model on load, never persisted.

	Model      string `yaml:"model" json:"model"`             // → config.yaml llm.model
	SmallModel string `yaml:"small_model" json:"small_model"` // → config.yaml llm.small_model

	// Pointers so "unset" and "zero" stay distinct: nil keeps the repo's value.
	// As plain floats, temperature 0 read as "never asked" and was unreachable.
	Temperature     *float64 `yaml:"temperature,omitempty" json:"temperature,omitempty"`             // → llm.temperature
	MaxOutputTokens *int     `yaml:"max_output_tokens,omitempty" json:"max_output_tokens,omitempty"` // → llm.max_output_tokens
	Timeout         *float64 `yaml:"timeout,omitempty" json:"timeout,omitempty"`                     // → llm.timeout

	// → core/.env: provider credential vars keyed by ENV-VAR NAME (e.g.
	Credentials map[string]string `yaml:"-" json:"-"`
}

type Git struct {
	Provider    string `yaml:"provider" json:"provider"`         // → config.yaml git.provider (GITHUB | AZURE_DEVOPS | GITLAB)
	AuthorName  string `yaml:"author_name" json:"author_name"`   // → config.yaml git.author_name
	AuthorEmail string `yaml:"author_email" json:"author_email"` // → config.yaml git.author_email

	// → core/.env: GIT_USER and GIT_TOKEN. The token is a secret.
	User  string `yaml:"-" json:"-"`
	Token string `yaml:"-" json:"-"`
}

// Cloud exists only to feed the renderer.
type Cloud struct {
	AWS        *AWSAuth        `yaml:"-" json:"-"`
	Azure      *AzureAuth      `yaml:"-" json:"-"`
	GCP        *GCPAuth        `yaml:"-" json:"-"`
	OCI        *OCIAuth        `yaml:"-" json:"-"`
	Kubernetes *KubernetesAuth `yaml:"-" json:"-"`
}

// AWSAuth → services/iac/.env AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION
// (or AWS_PROFILE, which mounts ~/.aws read-only).
type AWSAuth struct {
	Method    string `yaml:"-" json:"-"` // "static" | "profile"
	AccessKey string `yaml:"-" json:"-"` // → AWS_ACCESS_KEY_ID (secret)
	SecretKey string `yaml:"-" json:"-"` // → AWS_SECRET_ACCESS_KEY (secret)
	Region    string `yaml:"-" json:"-"` // → AWS_REGION
	Profile   string `yaml:"-" json:"-"` // → AWS_PROFILE
}

// AzureAuth → services/iac/.env ARM_TENANT_ID / ARM_CLIENT_ID / ARM_CLIENT_SECRET.
type AzureAuth struct {
	TenantID     string `yaml:"-" json:"-"` // → ARM_TENANT_ID
	ClientID     string `yaml:"-" json:"-"` // → ARM_CLIENT_ID
	ClientSecret string `yaml:"-" json:"-"` // → ARM_CLIENT_SECRET (secret)
}

// GCPAuth → services/iac/.env. A key file is mounted read-only; the inline
// JSON is the same key in the variable and needs no mount.
type GCPAuth struct {
	Method  string `yaml:"-" json:"-"` // "file" | "json"
	KeyFile string `yaml:"-" json:"-"` // host path → GOOGLE_APPLICATION_CREDENTIALS
	// InlineJSON → GOOGLE_CREDENTIALS (secret), for a host with no file to
	// mount. The repo's env.sample documents this form.
	InlineJSON string `yaml:"-" json:"-"`
}

// OCIAuth → services/iac/.env OCI_CONFIG_FILE (host path, mounted read-only).
type OCIAuth struct {
	ConfigPath string `yaml:"-" json:"-"`
}

// KubernetesAuth → services/iac/.env KUBE_CONFIG_PATH (host path, mounted read-only).
type KubernetesAuth struct {
	KubeconfigPath string `yaml:"-" json:"-"`
}

// Engine is the IaC engine the stack runs.
type Engine struct {
	Binary string `yaml:"-" json:"-"` // → services/iac/.env IAC_BINARY (tofu | terraform)

	// Wizard-only consent gate for Terraform's BUSL-1.1 license. Not persisted:
	// the form itself will not submit while this is false (tui.acknowledgeTerraform).
	BUSLAcknowledged bool `yaml:"-" json:"-"`
}

// Storage maps to config.yaml's `storage:` block. Its credentials are env vars
// in core/.env, or services/iac/.env for a repository-declared backend.
type Storage struct {
	// CLI discriminator, not a config key. Drives Provider and whether
	// TerraformStateBucket is empty.
	Model string `yaml:"-" json:"-"`

	Provider             string `yaml:"provider,omitempty" json:"provider,omitempty"`                             // → storage.provider: RUSTFS | S3 | STORAGE_ACCOUNT
	Bucket               string `yaml:"bucket,omitempty" json:"bucket,omitempty"`                                 // → storage.bucket (artifacts)
	TerraformStateBucket string `yaml:"terraform_state_bucket,omitempty" json:"terraform_state_bucket,omitempty"` // → storage.terraform_state_bucket ("" = repository-declared)
	Region               string `yaml:"region,omitempty" json:"region,omitempty"`                                 // → storage.region (ignored by STORAGE_ACCOUNT)
	EndpointURL          string `yaml:"endpoint_url,omitempty" json:"endpoint_url,omitempty"`                     // → storage.endpoint_url (in-cluster)
	PublicEndpointURL    string `yaml:"public_endpoint_url,omitempty" json:"public_endpoint_url,omitempty"`       // → storage.public_endpoint_url (browser-facing)

	// → core/.env, keyed by env-var name. Blank for S3: a static key would
	// defeat boto3's default chain.
	Credentials map[string]string `yaml:"-" json:"-"`

	// → services/iac/.env: backend credential variables for the repository-declared model.
	BackendCredentials map[string]string `yaml:"-" json:"-"`
}

type Notifications struct {
	Enabled bool `yaml:"enabled" json:"enabled"` // → config.yaml services.notifications.enabled

	// → SLACK_WEBHOOK_URL (secret). The service refuses to start without it,
	// so Enabled is only written when this is set.
	SlackWebhookURL string `yaml:"-" json:"-"`
}

// Secrets are generated, never user-supplied, never serialised.
type Secrets struct {
	// → core/.env and the matching sidecar .env (must be byte-identical).
	IACToken           string // KUMOSS_IAC_TOKEN
	NotificationsToken string // KUMOSS_NOTIFICATIONS_TOKEN
	MappingToken       string // KUMOSS_MAPPING_TOKEN
	AuthzToken         string // KUMOSS_AUTHZ_TOKEN

	// → core/.env. Never generated: docker-compose.yml fixes these, so they
	// come from the env sample and Fill carries them over on reconfigure.
	CoreDBPassword  string // embedded in KUMOSS_SQL_DATABASE_URL
	RustFSAccessKey string // RUSTFS_ACCESS_KEY
	RustFSSecretKey string // RUSTFS_SECRET_KEY
}
