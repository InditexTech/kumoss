// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package render

import (
	"context"
	"sort"
	"strings"
)

// Sample is one env file's key set, taken from the repo's env.sample. It decides
// which variables an env file carries: the sample lists them, the wizard fills
// the ones it owns and the sample supplies the rest.
type Sample struct {
	// Vars are the uncommented KEY=VALUE pairs, in file order.
	Vars []Var
}

// Var is one KEY=VALUE line of an env sample.
type Var struct {
	Key   string
	Value string
}

// Lookup returns the sample value for key and whether the key is in the sample.
// Unused by the pipeline today; kept as the sample's read accessor.
func (s *Sample) Lookup(key string) (string, bool) {
	for _, v := range s.Vars {
		if v.Key == key {
			return v.Value, true
		}
	}
	return "", false
}

// Keys returns the sample's keys in file order. Unused by the pipeline today.
func (s *Sample) Keys() []string {
	keys := make([]string, len(s.Vars))
	for i, v := range s.Vars {
		keys[i] = v.Key
	}
	return keys
}

// Samples are the three env samples, fetched once per run.
type Samples struct {
	Core          *Sample // core/env.sample
	IAC           *Sample // services/iac/env.sample
	Notifications *Sample // services/notifications/env.sample
}

// FetchSamples downloads and parses the three env samples. A failed fetch is
// returned, not fatal: the caller warns and falls back to the built-in key list,
// since the wizard can still write a usable (if possibly incomplete) set.
func FetchSamples(ctx context.Context, d *Download) (*Samples, error) {
	core, err := fetchSample(ctx, d, "core/env.sample")
	if err != nil {
		return nil, err
	}
	iac, err := fetchSample(ctx, d, "services/iac/env.sample")
	if err != nil {
		return nil, err
	}
	notifications, err := fetchSample(ctx, d, "services/notifications/env.sample")
	if err != nil {
		return nil, err
	}
	return &Samples{Core: core, IAC: iac, Notifications: notifications}, nil
}

// fetchSample downloads one env.sample and parses it.
func fetchSample(ctx context.Context, d *Download, path string) (*Sample, error) {
	raw, err := d.File(ctx, path)
	if err != nil {
		return nil, err
	}
	return ParseSample(string(raw)), nil
}

// ParseSample reads uncommented KEY=VALUE lines. Blank lines and comments are
// skipped, surrounding quotes are stripped, and a line with no `=` is ignored.
func ParseSample(body string) *Sample {
	s := &Sample{}
	for line := range strings.SplitSeq(body, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		s.Vars = append(s.Vars, Var{
			Key:   strings.TrimSpace(k),
			Value: strings.Trim(strings.TrimSpace(v), `"'`),
		})
	}
	return s
}

// NeedsAsking returns the keys of s that have no value and that owned does not
// cover, sorted so the form order is stable. These are the variables only the
// user can supply (e.g. SLACK_WEBHOOK_URL).
func (s *Sample) NeedsAsking(owned map[string]bool) []Var {
	var out []Var
	for _, v := range s.Vars {
		if v.Value == "" && !owned[v.Key] {
			out = append(out, v)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Key < out[j].Key })
	return out
}
