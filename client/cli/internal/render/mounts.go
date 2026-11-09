// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"path/filepath"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// Container paths where a mounted credential file lands. Each one matches the
// path the corresponding env var points at inside the container, so the value
// written to services/iac/.env works unchanged.
const (
	// ContainerCreds is the directory mounted from the host's credential
	// directory. The env var keeps the file's own base name, so a host path
	// ending in /gcp-sa.json is readable as /etc/kumoss/creds/gcp-sa.json.
	ContainerCreds = "/etc/kumoss/creds"
	// ContainerAWSProfile is the directory mounted from ~/.aws.
	ContainerAWSProfile = "/etc/kumoss/aws"
)

// Mount is one read-only host directory bind-mounted into a service. Source is
// the host path; compose resolves a relative one against the base compose
// file's directory (src/), so the pipeline passes a path relative to it.
type Mount struct {
	Service string // "iac"
	Source  string // host directory
	Target  string // container directory
}

// containerPath is where a host credential file lands: the fixed directory plus
// the file's own name, which is what cloudVars writes into services/iac/.env.
func containerPath(host string) string {
	return ContainerCreds + "/" + filepath.Base(host)
}

// IACMounts returns the credential mounts the answers need. A host path is a
// file, so its directory is mounted read-only; compose resolves a relative
// Source against the base compose file's directory, so Source must be relative
// to src/.
func IACMounts(s *state.State) []Mount {
	c := s.Cloud
	var mounts []Mount
	add := func(host string) {
		if host == "" {
			return
		}
		mounts = append(mounts, Mount{Service: "iac", Source: filepath.Dir(host), Target: ContainerCreds})
	}
	if c.GCP != nil && c.GCP.InlineJSON == "" {
		add(c.GCP.KeyFile)
	}
	if c.OCI != nil {
		add(c.OCI.ConfigPath)
	}
	if c.Kubernetes != nil {
		add(c.Kubernetes.KubeconfigPath)
	}
	if c.AWS != nil && c.AWS.Method == "profile" && c.AWS.Profile != "" {
		mounts = append(mounts, Mount{Service: "iac", Source: c.AWS.Profile, Target: ContainerAWSProfile})
	}
	return mounts
}
