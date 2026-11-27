// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package source

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// withBase points the fetcher at a local server.
func withBase(t *testing.T, url string) {
	t.Helper()
	old := rawBase
	rawBase = url
	t.Cleanup(func() { rawBase = old })
}

// Fetch returns the body, and the URL it asked for carries the tag and path.
func TestFetchReturnsBodyAndUsesTag(t *testing.T) {
	var gotPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		_, _ = w.Write([]byte("hello"))
	}))
	defer srv.Close()
	withBase(t, srv.URL)

	got, err := (&Fetcher{}).Fetch(context.Background(), "v1.2.3", "config.yaml")
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if string(got) != "hello" {
		t.Errorf("body = %q", got)
	}
	if want := "/v1.2.3/config.yaml"; gotPath != want {
		t.Errorf("path = %q, want %q", gotPath, want)
	}
}

// A non-200 must error, or a 404 body gets parsed as a file.
func TestFetchFailsOnNon200(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()
	withBase(t, srv.URL)

	if _, err := (&Fetcher{}).Fetch(context.Background(), "v1", "missing"); err == nil {
		t.Fatal("Fetch accepted a 404")
	}
}

// A cancelled context aborts the request instead of hanging.
func TestFetchHonoursContext(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}))
	defer srv.Close()
	withBase(t, srv.URL)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := (&Fetcher{}).Fetch(ctx, "v1", "x"); err == nil {
		t.Fatal("Fetch ignored a cancelled context")
	}
}

// A caller-supplied client is used as-is.
func TestFetchUsesTheInjectedClient(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	defer srv.Close()
	withBase(t, srv.URL)

	called := false
	f := &Fetcher{Client: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		called = true
		return http.DefaultTransport.RoundTrip(r)
	})}}
	if _, err := f.Fetch(context.Background(), "v1", "x"); err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if !called {
		t.Error("injected client was not used")
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
