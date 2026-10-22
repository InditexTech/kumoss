// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0
package answers

type Answers struct {
	SchemaVersion int           `yaml:"schema_version" json:"schema_version"`
	LLM           LLM           `yaml:"llm"           json:"llm"`
	Git           Git           `yaml:"git"           json:"git"`
	Cloud         Cloud         `yaml:"cloud"         json:"cloud"`
	Engine        Engine        `yaml:"engine"        json:"engine"`
	State         State         `yaml:"state"         json:"state"`
	Notifications Notifications `yaml:"notifications" json:"notifications"`
	Secrets       Secrets       `yaml:"-"             json:"-"` // never serialised
}

type LLM struct {
	Provider    string            `yaml:"provider"`    // "openai", "anthropic", …, "other"
	Model       string            `yaml:"model"`       // → config.yaml llm.model
	SmallModel  string            `yaml:"small_model"` // → config.yaml llm.small_model
	Credentials map[string]string `yaml:"-" json:"-"`  // e.g. OPENAI_API_KEY → value; never serialised, goes to .env
}

type Git struct {
	Provider    string `yaml:"provider"`     // GITHUB | GITLAB | AZURE_DEVOPS
	User        string `yaml:"user"`         // → GIT_USER
	Token       string `yaml:"token"`        // → GIT_TOKEN  (secret)
	AuthorName  string `yaml:"author_name"`  // optional
	AuthorEmail string `yaml:"author_email"` // optional
}

type Cloud struct {
	AWS        *AWSAuth        `yaml:"aws,omitempty"`
	Azure      *AzureAuth      `yaml:"azure,omitempty"`
	GCP        *GCPAuth        `yaml:"gcp,omitempty"`
	OCI        *OCIAuth        `yaml:"oci,omitempty"`
	Kubernetes *KubernetesAuth `yaml:"kubernetes,omitempty"`
}

type AWSAuth struct {
	Method    string `yaml:"method"`     // "static" | "profile"
	AccessKey string `yaml:"access_key"` // secret, method=static
	SecretKey string `yaml:"secret_key"` // secret, method=static
	Region    string `yaml:"region"`
	Profile   string `yaml:"profile"` // method=profile; mounts ~/.aws read-only
}

type AzureAuth struct {
	TenantID       string `yaml:"tenant_id"`
	ClientID       string `yaml:"client_id"`
	ClientSecret   string `yaml:"client_secret"` // secret
	SubscriptionID string `yaml:"subscription_id"`
}

type GCPAuth struct {
	KeyFile string `yaml:"key_file"` // path on host; contents → GOOGLE_CREDENTIALS
}

type OCIAuth struct {
	ConfigPath string `yaml:"config_path"` // host path, mounted read-only
}

type KubernetesAuth struct {
	KubeconfigPath string `yaml:"kubeconfig_path"` // → KUBE_CONFIG_PATH, mounted
}

type Engine struct {
	Binary           string `yaml:"binary"`            // "tofu" (default) | "terraform"
	BUSLAcknowledged bool   `yaml:"busl_acknowledged"` // required when binary == terraform
}

type State struct {
	Model string `yaml:"model"` // "bundled" | "external_s3" | "external_azure" | "repository"

	// external_s3
	S3Bucket          string `yaml:"s3_bucket,omitempty"`
	S3ArtifactsBucket string `yaml:"s3_artifacts_bucket,omitempty"`
	S3Region          string `yaml:"s3_region,omitempty"`
	S3AccessKey       string `yaml:"s3_access_key,omitempty"` // empty = default credential chain
	S3SecretKey       string `yaml:"s3_secret_key,omitempty"` // secret

	// external_azure
	StorageAccount         string `yaml:"storage_account,omitempty"`
	StorageAccountEndpoint string `yaml:"storage_account_endpoint,omitempty"`
	StateContainer         string `yaml:"state_container,omitempty"`
	ArtifactsContainer     string `yaml:"artifacts_container,omitempty"`
	StorageAccountKey      string `yaml:"storage_account_key,omitempty"` // secret

	// repository: backend credentials the sidecar needs, as raw env vars
	BackendCredentials map[string]string `yaml:"backend_credentials,omitempty"`
}

type Notifications struct {
	Enabled         bool   `yaml:"enabled"`
	SlackWebhookURL string `yaml:"slack_webhook_url,omitempty"` // secret
}

type Secrets struct {
	IACToken           string
	NotificationsToken string
	MappingToken       string
	AuthzToken         string

	// Only generated on a fresh install; reused when the volumes already exist.
	CoreDBPassword  string
	RustFSAccessKey string
	RustFSSecretKey string
}
