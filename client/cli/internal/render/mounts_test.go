// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"os"
	"path"
	"path/filepath"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// The env var must name the container path, not the host one: anything else is
// an auth failure at plan time.
func TestCloudKeyFilesAreMountedAndPointedAt(t *testing.T) {
	s := &state.State{Cloud: state.Cloud{
		GCP:        &state.GCPAuth{KeyFile: "/home/me/gcp.json"},
		Kubernetes: &state.KubernetesAuth{KubeconfigPath: "/home/me/kube/config"},
	}}
	vars := cloudVars(s.Cloud)
	if vars["GOOGLE_APPLICATION_CREDENTIALS"] != "/etc/kumoss/creds/gcp/gcp.json" {
		t.Errorf("GCP credentials = %q", vars["GOOGLE_APPLICATION_CREDENTIALS"])
	}
	if vars["KUBE_CONFIG_PATH"] != "/etc/kumoss/creds/kubernetes/config" {
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
		"/home/me:/etc/kumoss/creds/gcp:ro":             true,
		"/home/me/kube:/etc/kumoss/creds/kubernetes:ro": true,
	}
	for _, v := range volumes {
		delete(want, v.(string))
	}
	if len(want) != 0 {
		t.Errorf("missing mounts %v in %v", want, volumes)
	}
}

// Two clouds need two mount points: sharing one, compose keeps the last bind
// and drops the rest, leaving the first env var pointing at nothing.
func TestEachCloudGetsItsOwnMountPoint(t *testing.T) {
	s := &state.State{Cloud: state.Cloud{
		GCP:        &state.GCPAuth{Method: "file", KeyFile: "/home/me/gcp/sa.json"},
		OCI:        &state.OCIAuth{ConfigPath: "/home/me/oci/config"},
		Kubernetes: &state.KubernetesAuth{KubeconfigPath: "/home/me/kube/config"},
	}}

	mounts := IACMounts(s)
	if len(mounts) != 3 {
		t.Fatalf("mounts = %v, want one per cloud", mounts)
	}
	seen := map[string]string{}
	for _, m := range mounts {
		if prev, dup := seen[m.Target]; dup {
			t.Fatalf("%s and %s both mount at %s; compose keeps only one", prev, m.Source, m.Target)
		}
		seen[m.Target] = m.Source
	}

	// Each var must resolve inside its own mount, or the engine looks elsewhere.
	vars := cloudVars(s.Cloud)
	for _, c := range []struct{ env, host string }{
		{"GOOGLE_APPLICATION_CREDENTIALS", "/home/me/gcp"},
		{"OCI_CONFIG_FILE", "/home/me/oci"},
		{"KUBE_CONFIG_PATH", "/home/me/kube"},
	} {
		got := vars[c.env]
		target, ok := seen[path.Dir(got)]
		if !ok {
			t.Errorf("%s = %q, which is not inside any mount %v", c.env, got, seen)
			continue
		}
		if target != c.host {
			t.Errorf("%s = %q, which is inside the mount of %s, not %s", c.env, got, target, c.host)
		}
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

// No key must not become a directory path, or the engine opens that instead of
// falling back to Application Default Credentials.
func TestGCPWithoutAKeyLeavesThePathEmpty(t *testing.T) {
	vars := cloudVars(state.Cloud{GCP: &state.GCPAuth{Method: "file"}})
	if v := vars["GOOGLE_APPLICATION_CREDENTIALS"]; v != "" {
		t.Errorf("GOOGLE_APPLICATION_CREDENTIALS = %q, want empty", v)
	}
}

// A mount alone leaves the engine reading the image's own empty ~/.aws.
func TestAWSProfilePointsAtTheMountedDirectory(t *testing.T) {
	vars := cloudVars(state.Cloud{AWS: &state.AWSAuth{Method: "profile", Profile: "prod", Region: "eu-west-1"}})
	if vars["AWS_SHARED_CREDENTIALS_FILE"] != "/etc/kumoss/aws/credentials" {
		t.Errorf("AWS_SHARED_CREDENTIALS_FILE = %q", vars["AWS_SHARED_CREDENTIALS_FILE"])
	}
	if vars["AWS_ACCESS_KEY_ID"] != "" {
		t.Errorf("static key written for a profile install: %q", vars["AWS_ACCESS_KEY_ID"])
	}
}

// No cloud picked: no mounts, and no iac block in the override.
func TestNoMountsLeavesIacAlone(t *testing.T) {
	if got := IACMounts(&state.State{}); len(got) != 0 {
		t.Fatalf("mounts = %v, want none", got)
	}
}

// The named-profile method must mount the host's ~/.aws. AWS_PROFILE is a
// profile name, not a path: mounting it bound a directory called "prod".
func TestAWSProfileMountsTheHostAWSDirectory(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil {
		t.Skip("no home directory")
	}
	mounts := IACMounts(&state.State{Cloud: state.Cloud{
		AWS: &state.AWSAuth{Method: "profile", Profile: "prod", Region: "eu-west-1"},
	}})
	if len(mounts) != 1 {
		t.Fatalf("mounts = %v, want one", mounts)
	}
	if want := filepath.Join(home, ".aws"); mounts[0].Source != want {
		t.Errorf("Source = %q, want %q", mounts[0].Source, want)
	}
	if mounts[0].Target != ContainerAWSProfile {
		t.Errorf("Target = %q, want %q", mounts[0].Target, ContainerAWSProfile)
	}
}

// Static keys need no file, so nothing is mounted.
func TestAWSStaticKeysMountNothing(t *testing.T) {
	mounts := IACMounts(&state.State{Cloud: state.Cloud{
		AWS: &state.AWSAuth{Method: "static", AccessKey: "AKIA", SecretKey: "s3cret"},
	}})
	if len(mounts) != 0 {
		t.Errorf("mounts = %v, want none", mounts)
	}
}
