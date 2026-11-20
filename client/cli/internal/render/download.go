// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"context"
	"os"
	"path/filepath"
)

// Download fetches repo files at a release tag: the CLI ships without the
// repo, so anything it needs at runtime is downloaded.
type Download struct {
	// Fetch is injected by the composition root, so this package depends on no
	// concrete downloader. A func, not an interface, so tests stub it inline.
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

// writeFile creates the parent directory then writes the bytes with mode,
// atomically: a temp file in the same directory, then a rename. A crash mid-write
// would otherwise leave a truncated .env — the only copy of the stack's tokens.
func writeFile(path string, data []byte, mode os.FileMode) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name()) // no-op once the rename succeeded
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}
