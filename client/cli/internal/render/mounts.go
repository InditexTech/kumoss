// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"os"
	"path/filepath"

	"github.com/InditexTech/kumoss/client/cli/internal/state"
)

// Container paths where a mounted credential file lands. Each one matches the
// path the corresponding env var points at inside the container, so the value
// written to services/iac/.env works unchanged.
const (
	// ContainerCreds is the parent of the per-cloud credential directories.
	ContainerCreds = "/etc/kumoss/creds"
	// ContainerAWSProfile is the directory mounted from ~/.aws.
	ContainerAWSProfile = "/etc/kumoss/aws"
)

// Per-cloud subdirectory names, shared with cloudVars so the mount target and
// the env var cannot drift apart.
const (
	cloudGCP  = "gcp"
	cloudOCI  = "oci"
	cloudKube = "kubernetes"
)

// credsDir gives each cloud its own mount point. Sharing one, compose keeps the
// last bind and silently drops the rest.
func credsDir(cloud string) string {
	return ContainerCreds + "/" + cloud
}

// Mount is one read-only host directory bind-mounted into a service. Source is
// the host path; compose resolves a relative one against the base compose
// file's directory (src/), so the pipeline passes a path relative to it.
type Mount struct {
	Service string // "iac"
	Source  string // host directory
	Target  string // container directory
}

// containerPath is where one cloud's credential file lands, and what cloudVars
// writes into services/iac/.env.
func containerPath(cloud, host string) string {
	return credsDir(cloud) + "/" + filepath.Base(host)
}

// awsHomeDir is the host ~/.aws the named-profile method needs. AWS_PROFILE is
// a profile name, not a path: mounting it bound a directory of that name and
// the credentials never arrived. Empty means no mount, rather than a broken one.
func awsHomeDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".aws")
}

// IACMounts returns the credential mounts the answers need. A host path is a
// file, so its directory is mounted read-only; compose resolves a relative
// Source against the base compose file's directory, so Source must be relative
// to src/.
func IACMounts(s *state.State) []Mount {
	c := s.Cloud
	var mounts []Mount
	add := func(cloud, host string) {
		if host == "" {
			return
		}
		mounts = append(mounts, Mount{Service: "iac", Source: filepath.Dir(host), Target: credsDir(cloud)})
	}
	if c.GCP != nil && c.GCP.InlineJSON == "" {
		add(cloudGCP, c.GCP.KeyFile)
	}
	if c.OCI != nil {
		add(cloudOCI, c.OCI.ConfigPath)
	}
	if c.Kubernetes != nil {
		add(cloudKube, c.Kubernetes.KubeconfigPath)
	}
	if c.AWS != nil && c.AWS.Method == "profile" && c.AWS.Profile != "" {
		if dir := awsHomeDir(); dir != "" {
			mounts = append(mounts, Mount{Service: "iac", Source: dir, Target: ContainerAWSProfile})
		}
	}
	return mounts
}
