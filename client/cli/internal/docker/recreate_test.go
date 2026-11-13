// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package docker

import (
	"reflect"
	"testing"
)

// Recreate is `up -d <svc>`: restart would keep the old environment.
func TestRecreateNamesTheServices(t *testing.T) {
	c := &Compose{ProjectDir: "/h/.kumoss", Files: []string{"src/docker-compose.yml"}}
	got := c.args(append([]string{"up", "-d"}, "core", "iac")...)
	want := []string{"compose", "-f", "src/docker-compose.yml", "up", "-d", "core", "iac"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("args = %v, want %v", got, want)
	}
}

// The logs flags are passthrough: compose already understands 30m and a
// timestamp, so the CLI must not parse them.
func TestLogsPassesFlagsThrough(t *testing.T) {
	c := &Compose{ProjectDir: "/h/.kumoss", Files: []string{"src/docker-compose.yml"}}
	got := c.args("logs", "-f", "--since", "30m", "core")
	want := []string{"compose", "-f", "src/docker-compose.yml", "logs", "-f", "--since", "30m", "core"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("args = %v, want %v", got, want)
	}
}
