// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"context"
	"os"
	"path/filepath"
)

// Download fetches a file from the Kumoss repository at a release tag. It is the
// one place that knows how a repo file becomes a local file: the CLI ships
// without the repo, so anything it needs at runtime comes from the tag reported
// by buildinfo.KumossTag().
type Download struct {
	// Fetch downloads a repo file at the release tag. Required: the caller (the
	// composition root) injects it, so this package never depends on a concrete
	// downloader. A function, not a fetcher type, so tests can stub it inline.
	Fetch func(ctx context.Context, tag, path string) ([]byte, error)
	// Tag is the release tag to fetch (buildinfo.KumossTag()).
	Tag string
}

// File returns the bytes of a repo-relative path at the tag.
func (d *Download) File(ctx context.Context, path string) ([]byte, error) {
	return d.Fetch(ctx, d.Tag, path)
}

// Save fetches path and writes it verbatim to dst, creating parent directories.
// Used for files the pipeline consumes as-is (the compose file), not renders.
func (d *Download) Save(ctx context.Context, repoPath, dst string) error {
	raw, err := d.File(ctx, repoPath)
	if err != nil {
		return err
	}
	return writeFile(dst, raw, 0o644)
}

// Example fetches path and writes it verbatim to example, so the user keeps the
// comments the generated file loses. Returns the fetched bytes so the caller can
// render them too, without a second download.
func (d *Download) Example(ctx context.Context, repoPath, example string) ([]byte, error) {
	raw, err := d.File(ctx, repoPath)
	if err != nil {
		return nil, err
	}
	if err := writeFile(example, raw, 0o644); err != nil {
		return nil, err
	}
	return raw, nil
}

// writeFile creates the parent directory then writes the bytes with mode.
func writeFile(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, data, mode)
}
