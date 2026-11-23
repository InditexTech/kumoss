// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package docker

import (
	"context"
	"encoding/json"
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
	// CreatedAt is RFC 3339. Compose has no Created field, so a name that
	// matched nothing left every container looking brand new.
	CreatedAt time.Time `json:"CreatedAt"`
	// RestartCount is absent on older Compose releases; the zero reads as
	// "none yet", the same thing it prints for a fresh container.
	RestartCount int `json:"RestartCount"`
}

// PS returns the stack's containers. The output is parsed here, not by compose
// itself, so the CLI needs no template.
func (c *Compose) PS(ctx context.Context) ([]PS, error) {
	out, err := c.run(ctx, "ps", "--all", "--format", "json")
	if err != nil {
		return nil, err
	}
	return ParsePS(out), nil
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
