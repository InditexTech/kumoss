// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

// stubDownload returns a Download whose fetch serves one body and records the
// tag/path it was asked for.
func stubDownload(t *testing.T, body string, wantTag, wantPath string) *Download {
	t.Helper()
	return &Download{
		Tag: wantTag,
		Fetch: func(_ context.Context, tag, path string) ([]byte, error) {
			if tag != wantTag || path != wantPath {
				t.Errorf("fetched %s at %s, want %s at %s", path, tag, wantPath, wantTag)
			}
			return []byte(body), nil
		},
	}
}

// File is the thin pass-through the rest of the pipeline relies on.
func TestDownloadFile(t *testing.T) {
	d := stubDownload(t, "body", "v1", "x.yml")
	got, err := d.File(context.Background(), "x.yml")
	if err != nil {
		t.Fatalf("File: %v", err)
	}
	if string(got) != "body" {
		t.Errorf("File = %q", got)
	}
}

// Save creates the parent: the compose file lives under src/, which may not
// exist yet.
func TestDownloadSaveCreatesParents(t *testing.T) {
	dst := filepath.Join(t.TempDir(), "src", "nested", "docker-compose.yml")
	d := stubDownload(t, "services: {}\n", "v1", "docker-compose.yml")

	if err := d.Save(context.Background(), "docker-compose.yml", dst); err != nil {
		t.Fatalf("Save: %v", err)
	}
	raw, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if string(raw) != "services: {}\n" {
		t.Errorf("content = %q", raw)
	}
	info, err := os.Stat(dst)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if perm := info.Mode().Perm(); perm != 0o644 {
		t.Errorf("mode = %o, want 644", perm)
	}
}

// A fetch failure must reach the caller, and must not leave a file behind.
func TestDownloadSavePropagatesFetchError(t *testing.T) {
	dst := filepath.Join(t.TempDir(), "x.yml")
	d := &Download{Tag: "v1", Fetch: func(context.Context, string, string) ([]byte, error) {
		return nil, errors.New("offline")
	}}
	if err := d.Save(context.Background(), "x.yml", dst); err == nil {
		t.Fatal("Save swallowed the fetch error")
	}
	if _, err := os.Stat(dst); !os.IsNotExist(err) {
		t.Error("Save wrote a file despite the fetch failing")
	}
}

// Example returns the bytes it wrote, so the caller needs no second download.
func TestDownloadExampleReturnsAndWrites(t *testing.T) {
	example := filepath.Join(t.TempDir(), "config", "config.yaml.example")
	d := stubDownload(t, "# sample\n", "v1", "config.yaml")

	got, err := d.Example(context.Background(), "config.yaml", example)
	if err != nil {
		t.Fatalf("Example: %v", err)
	}
	if string(got) != "# sample\n" {
		t.Errorf("returned bytes = %q", got)
	}
	raw, err := os.ReadFile(example)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if string(raw) != string(got) {
		t.Errorf("file = %q, returned = %q", raw, got)
	}
}

// writeFile is shared by Save and Example; a failed mkdir must not be ignored.
func TestWriteFileFailsWhenParentIsAFile(t *testing.T) {
	dir := t.TempDir()
	blocker := filepath.Join(dir, "file")
	if err := os.WriteFile(blocker, nil, 0o644); err != nil {
		t.Fatalf("write blocker: %v", err)
	}
	if err := writeFile(filepath.Join(blocker, "child"), []byte("x"), 0o644); err == nil {
		t.Error("writeFile succeeded under a regular file")
	}
}
