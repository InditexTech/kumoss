// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// A key file the iac container cannot see is an auth failure at plan time, and
// the env var must name the path inside the container, not the host path.
func TestCloudKeyFilesAreMountedAndPointedAt(t *testing.T) {
	s := &state.State{Cloud: state.Cloud{
		GCP:        &state.GCPAuth{KeyFile: "/home/me/gcp.json"},
		Kubernetes: &state.KubernetesAuth{KubeconfigPath: "/home/me/kube/config"},
	}}
	vars := cloudVars(s.Cloud)
	if vars["GOOGLE_APPLICATION_CREDENTIALS"] != "/etc/kumoss/creds/gcp.json" {
		t.Errorf("GCP credentials = %q", vars["GOOGLE_APPLICATION_CREDENTIALS"])
	}
	if vars["KUBE_CONFIG_PATH"] != "/etc/kumoss/creds/config" {
		t.Errorf("KUBE_CONFIG_PATH = %q", vars["KUBE_CONFIG_PATH"])
	}

	out, err := (&Compose{ConfigPath: "../config/config.yaml", Mounts: IACMounts(s)}).Render()
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	var doc map[string]any
	if err := yaml.Unmarshal(out, &doc); err != nil {
		t.Fatalf("parse: %v", err)
	}
	iac := doc["services"].(map[string]any)["iac"].(map[string]any)
	volumes := iac["volumes"].([]any)
	want := map[string]bool{
		"/home/me:/etc/kumoss/creds:ro":      true,
		"/home/me/kube:/etc/kumoss/creds:ro": true,
	}
	for _, v := range volumes {
		delete(want, v.(string))
	}
	if len(want) != 0 {
		t.Errorf("missing mounts %v in %v", want, volumes)
	}
}

// The inline JSON is the whole credential in one env var: no file, no mount.
func TestGCPInlineJSONNeedsNoMount(t *testing.T) {
	s := &state.State{Cloud: state.Cloud{GCP: &state.GCPAuth{
		Method: "json", InlineJSON: `{"type":"service_account"}`, KeyFile: "/ignored/key.json",
	}}}
	vars := cloudVars(s.Cloud)
	if vars["GOOGLE_CREDENTIALS"] != `{"type":"service_account"}` {
		t.Errorf("GOOGLE_CREDENTIALS = %q", vars["GOOGLE_CREDENTIALS"])
	}
	if v, ok := vars["GOOGLE_APPLICATION_CREDENTIALS"]; ok {
		t.Errorf("path written alongside the inline key: %q", v)
	}
	if got := IACMounts(s); len(got) != 0 {
		t.Errorf("mounts = %v, want none for an inline key", got)
	}
}

// No key at all must not become a path to a directory: the engine then tries
// to open /etc/kumoss/creds/ and fails instead of using Application Default
// Credentials.
func TestGCPWithoutAKeyLeavesThePathEmpty(t *testing.T) {
	vars := cloudVars(state.Cloud{GCP: &state.GCPAuth{Method: "file"}})
	if v := vars["GOOGLE_APPLICATION_CREDENTIALS"]; v != "" {
		t.Errorf("GOOGLE_APPLICATION_CREDENTIALS = %q, want empty", v)
	}
}

// The profile method reads ~/.aws/credentials by default; a mount alone leaves
// the engine looking at the image's empty ~/.aws.
func TestAWSProfilePointsAtTheMountedDirectory(t *testing.T) {
	vars := cloudVars(state.Cloud{AWS: &state.AWSAuth{Method: "profile", Profile: "prod", Region: "eu-west-1"}})
	if vars["AWS_SHARED_CREDENTIALS_FILE"] != "/etc/kumoss/aws/credentials" {
		t.Errorf("AWS_SHARED_CREDENTIALS_FILE = %q", vars["AWS_SHARED_CREDENTIALS_FILE"])
	}
	if vars["AWS_ACCESS_KEY_ID"] != "" {
		t.Errorf("static key written for a profile install: %q", vars["AWS_ACCESS_KEY_ID"])
	}
}

// With no cloud picked there is nothing to mount, and the override must not
// gain an iac service block.
func TestNoMountsLeavesIacAlone(t *testing.T) {
	if got := IACMounts(&state.State{}); len(got) != 0 {
		t.Fatalf("mounts = %v, want none", got)
	}
}
