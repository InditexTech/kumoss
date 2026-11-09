// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package release

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// A missing archive must not be served as if it were the binary, and the
// checksum lookup must match the exact file, not a substring of another name.
func TestFetchRejectsNon200AndLookupMatchesExactName(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/kumoss_1.2.3_linux_amd64.tar.gz" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte("archive"))
	}))
	defer srv.Close()
	old := endpoints
	endpoints = []string{srv.URL}
	defer func() { endpoints = old }()

	if body, err := Fetch(context.Background(), "kumoss_1.2.3_linux_amd64.tar.gz"); err != nil || string(body) != "archive" {
		t.Fatalf("Fetch = %q, %v", body, err)
	}
	if _, err := Fetch(context.Background(), "kumoss_1.2.3_linux_arm64.tar.gz"); err == nil {
		t.Fatal("Fetch accepted a 404")
	}

	sums := []byte("aaaa  kumoss_1.2.3_linux_amd64.tar.gz\nbbbb  kumoss_1.2.3_linux_amd64.tar.gz.sig\n")
	if got, err := Lookup(sums, "kumoss_1.2.3_linux_amd64.tar.gz"); err != nil || got != "aaaa" {
		t.Errorf("Lookup = %q, %v", got, err)
	}
	if _, err := Lookup(sums, "kumoss_9_linux_amd64.tar.gz"); err == nil {
		t.Error("Lookup matched a name that is not listed")
	}
}
