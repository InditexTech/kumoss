// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package docker

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// PS is one row of `docker compose ps --format json`. Compose emits one JSON
// object per line, not an array.
type PS struct {
	Name    string `json:"Name"`
	Service string `json:"Service"`
	State   string `json:"State"`  // running, exited, restarting…
	Status  string `json:"Status"` // "Up 3 minutes (healthy)"
	Health  string `json:"Health"` // healthy, unhealthy, "" when no check
	// CreatedAt is when the container was created, so a name that matched
	// nothing no longer leaves every container looking brand new. See Time.
	CreatedAt Time `json:"CreatedAt"`
	// RestartCount is absent on older Compose releases; the zero reads as
	// "none yet", the same thing it prints for a fresh container.
	RestartCount int `json:"RestartCount"`
}

// PS returns the stack's containers. The output is parsed here, not by compose
// itself, so the CLI needs no template.
func (c *Compose) PS(ctx context.Context) ([]PS, error) {
	// Without a -f compose searches the working directory for a default file,
	// and the home root has none: it would read an empty project instead of
	// this home's stack.
	if len(c.Files) == 0 {
		return nil, fmt.Errorf("no compose file in %s: the install is incomplete, run kumoss init", c.ProjectDir)
	}
	out, err := c.run(ctx, "ps", "--all", "--format", "json")
	if err != nil {
		return nil, err
	}
	return ParsePS(out), nil
}

// Time is the CreatedAt column. Compose prints RFC 3339 on Linux and
// "2006-01-02 15:04:05 -0700 MST" on Docker Desktop, so both are read. A
// time.Time field took only the first and dropped the whole row on the
// second, which made a running stack list as empty. Anything else is zero,
// and the caller treats zero as "unknown".
type Time struct{ time.Time }

func (t *Time) UnmarshalJSON(b []byte) error {
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return err
	}
	parsed, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		parsed, err = time.Parse("2006-01-02 15:04:05 -0700 MST", s)
	}
	if err != nil {
		t.Time = time.Time{}
		return nil
	}
	t.Time = parsed
	return nil
}

// ParsePS reads compose's line-delimited JSON. A blank line or a malformed one
// is skipped: one unreadable container must not hide the others.
func ParsePS(out string) []PS {
	var rows []PS
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var p PS
		if err := json.Unmarshal([]byte(line), &p); err != nil {
			continue
		}
		rows = append(rows, p)
	}
	return rows
}
