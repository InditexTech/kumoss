// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Package release reaches the public release endpoints: the install script
// `kumoss self-install` runs, and the archives it downloads. It is not a
// substitute for curl or wget, which install.sh requires.
package release

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// endpoints are the two URLs a file can live at. A var, for tests.
var endpoints = []string{
	"https://github.com/InditexTech/kumoss/releases/latest/download",
	"https://raw.githubusercontent.com/InditexTech/kumoss/main",
}

// Fetch returns a file's body, trying each endpoint in turn.
func Fetch(ctx context.Context, name string) ([]byte, error) {
	var last error
	for _, base := range endpoints {
		body, err := get(ctx, base+"/"+name)
		if err == nil {
			return body, nil
		}
		last = err
	}
	return nil, last
}

func get(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := (&http.Client{Timeout: 5 * time.Minute}).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fetch %s: %s", url, resp.Status)
	}
	return io.ReadAll(resp.Body)
}

// Script is install.sh at the tip of main, so self-install runs the current
// installer and not a copy baked into an old binary.
func Script(ctx context.Context) ([]byte, error) {
	return get(ctx, endpoints[1]+"/install.sh")
}

// Checksums returns checksums.txt from the latest release.
func Checksums(ctx context.Context) ([]byte, error) {
	return Fetch(ctx, "checksums.txt")
}

// Archive returns one platform archive, e.g. kumoss_1.2.3_linux_amd64.tar.gz.
func Archive(ctx context.Context, name string) ([]byte, error) {
	return Fetch(ctx, name)
}

// Lookup returns the expected SHA-256 for name from a checksums.txt body.
func Lookup(checksums []byte, name string) (string, error) {
	for _, line := range strings.Split(string(checksums), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && strings.TrimPrefix(fields[1], "*") == name {
			return fields[0], nil
		}
	}
	return "", fmt.Errorf("%s not listed in checksums.txt", name)
}
