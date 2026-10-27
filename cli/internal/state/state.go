// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package state

type State struct {
	SchemaVersion int     `yaml:"schema_version" json:"schema_version"`
	LLM           LLM     `yaml:"llm"            json:"llm"`
	Git           Git     `yaml:"git"            json:"git"`
	Cloud         Cloud   `yaml:"-"              json:"-"`
	Engine        Engine  `yaml:"-"              json:"-"`
	Storage       Storage `yaml:"storage"        json:"storage"`
	// Notifications Notifications `yaml:"notifications"  json:"notifications"`
	Secrets Secrets `yaml:"-"              json:"-"`
}

type LLM struct {
	Provider string `yaml:"-" json:"-"` // Wizard-only: which provider row was picked. Used to derive the model-id prefix and the credential variable names. Re-derived from llm.model on load, never persisted.

	Model      string `yaml:"model" json:"model"`             // → config.yaml llm.model
	SmallModel string `yaml:"small_model" json:"small_model"` // → config.yaml llm.small_model

	Temperature     float64 `yaml:"temperature,omitempty" json:"temperature,omitempty"`             // → llm.temperature
	MaxOutputTokens int     `yaml:"max_output_tokens,omitempty" json:"max_output_tokens,omitempty"` // → llm.max_output_tokens
	Timeout         float64 `yaml:"timeout,omitempty" json:"timeout,omitempty"`                     // → llm.timeout

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

// Exists only to feed the renderer.
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
// (ARM_SUBSCRIPTION_ID is injected per request from the scope, never set here.)
type AzureAuth struct {
	TenantID       string `yaml:"-" json:"-"` // → ARM_TENANT_ID
	ClientID       string `yaml:"-" json:"-"` // → ARM_CLIENT_ID
	ClientSecret   string `yaml:"-" json:"-"` // → ARM_CLIENT_SECRET (secret)
	SubscriptionID string `yaml:"-" json:"-"` // → ARM_SUBSCRIPTION_ID
}

// GCPAuth → services/iac/.env GOOGLE_APPLICATION_CREDENTIALS (key-file path mounted
// read-only into the iac container).
type GCPAuth struct {
	KeyFile string `yaml:"-" json:"-"` // host path → GOOGLE_APPLICATION_CREDENTIALS
}

// OCIAuth → services/iac/.env OCI_CONFIG_FILE (host path, mounted read-only).
type OCIAuth struct {
	ConfigPath string `yaml:"-" json:"-"`
}

// KubernetesAuth → services/iac/.env KUBE_CONFIG_PATH (host path, mounted read-only).
type KubernetesAuth struct {
	KubeconfigPath string `yaml:"-" json:"-"`
}

// IAC_BINARY env var in services/iac/.env (tofu | terraform).
type Engine struct {
	Binary string `yaml:"-" json:"-"` // → services/iac/.env IAC_BINARY

	// Wizard-only consent gate for Terraform's BUSL-1.1 license. Not persisted anywhere.
	BUSLAcknowledged bool `yaml:"-" json:"-"`
}

// Storage fields map to config.yaml's `storage:` block; credentials are
// env vars in core/.env (RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY / STORAGE_ACCOUNT_KEY) and
// services/iac/.env (repository-declared backend creds).
type Storage struct {
	// CLI discriminator (not a config key): "bundled" | "external_s3" | "external_azure" |
	// "repository". Drives Provider and the empty/non-empty TerraformStateBucket.
	Model string `yaml:"-" json:"-"`

	Provider             string `yaml:"provider,omitempty" json:"provider,omitempty"`                             // → storage.provider: RUSTFS | S3 | STORAGE_ACCOUNT
	Bucket               string `yaml:"bucket,omitempty" json:"bucket,omitempty"`                                 // → storage.bucket (artifacts)
	TerraformStateBucket string `yaml:"terraform_state_bucket,omitempty" json:"terraform_state_bucket,omitempty"` // → storage.terraform_state_bucket ("" = repository-declared)
	Region               string `yaml:"region,omitempty" json:"region,omitempty"`                                 // → storage.region (ignored by STORAGE_ACCOUNT)
	EndpointURL          string `yaml:"endpoint_url,omitempty" json:"endpoint_url,omitempty"`                     // → storage.endpoint_url (in-cluster)
	PublicEndpointURL    string `yaml:"public_endpoint_url,omitempty" json:"public_endpoint_url,omitempty"`       // → storage.public_endpoint_url (browser-facing)

	// → core/.env: RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY / STORAGE_ACCOUNT_KEY, keyed by
	// ENV-VAR NAME. Blank for provider S3 (a static key would defeat boto3's chain).
	Credentials map[string]string `yaml:"-" json:"-"`

	// → services/iac/.env: backend credential variables for the repository-declared model.
	BackendCredentials map[string]string `yaml:"-" json:"-"`
}

// type Notifications struct {
// 	Enabled bool `yaml:"enabled" json:"enabled"` // → config.yaml services.notifications.enabled

// 	// → services/notifications/.env SLACK_WEBHOOK_URL (secret).
// 	SlackWebhookURL string `yaml:"-" json:"-"`
// }

// Generated, never user-supplied, never serialised. Every value
// is an env var in core/.env or a sidecar .env.
type Secrets struct {
	// → core/.env and the matching sidecar .env (must be byte-identical).
	IACToken           string // KUMOSS_IAC_TOKEN
	NotificationsToken string // KUMOSS_NOTIFICATIONS_TOKEN
	MappingToken       string // KUMOSS_MAPPING_TOKEN
	AuthzToken         string // KUMOSS_AUTHZ_TOKEN

	// → core/.env, only generated on a fresh install; reused when the volumes exist.
	CoreDBPassword  string // embedded in KUMOSS_SQL_DATABASE_URL
	RustFSAccessKey string // RUSTFS_ACCESS_KEY
	RustFSSecretKey string // RUSTFS_SECRET_KEY
}
