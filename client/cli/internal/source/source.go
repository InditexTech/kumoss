// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package source fetches files from the Kumoss repository at a release tag.
// The CLI ships without the repo, so anything it needs at runtime (the compose
// file, the default config.yaml) comes from raw.githubusercontent.com at the
// tag reported by buildinfo.KumossTag().
package source

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"
)

// rawBase is the raw-content host. It is a var so tests can point at a local
// server.
var rawBase = "https://raw.githubusercontent.com/InditexTech/kumoss"

// Fetcher downloads repo files. Client is the HTTP client; nil uses a default
// with a timeout.
type Fetcher struct {
	Client *http.Client
}

// Fetch returns the bytes of repo-relative path at tag, e.g.
// Fetch(ctx, "v1.2.3", "config.yaml").
func (f *Fetcher) Fetch(ctx context.Context, tag, path string) ([]byte, error) {
	url := fmt.Sprintf("%s/%s/%s", rawBase, tag, path)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	client := f.Client
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fetch %s: %s", url, resp.Status)
	}
	return io.ReadAll(resp.Body)
}
