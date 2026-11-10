// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"strings"
	"testing"
)

// Whitespace is written to .env verbatim, so it must not pass as a value.
func TestRequired(t *testing.T) {
	for _, v := range []string{"", "   ", "\t\n"} {
		if err := required(v); err == nil {
			t.Errorf("required(%q) = nil, want error", v)
		}
	}
	if err := required(" x "); err != nil {
		t.Errorf("required(\" x \") = %v", err)
	}
}

// email is deliberately loose, but must catch the common typos.
func TestEmail(t *testing.T) {
	cases := []struct {
		in   string
		ok   bool
		note string
	}{
		{"a@b", true, "minimal valid"},
		{"bot@example.invalid", true, "valid"},
		{"@b", false, "no local part"},
		{"a@", false, "no domain"},
		{"ab", false, "no at sign"},
		{"a b@c", false, "space"},
		{"a@b\tc", false, "tab"},
	}
	for _, c := range cases {
		err := email(c.in)
		if (err == nil) != c.ok {
			t.Errorf("email(%q) = %v, want ok=%v (%s)", c.in, err, c.ok, c.note)
		}
	}
}

// Each must reject unparseable text and out-of-range numbers.
func TestFloatRange(t *testing.T) {
	check := floatRange(0, 1)
	for _, v := range []string{"0", "0.5", "1", " 0.25 ", ""} {
		if err := check(v); err != nil {
			t.Errorf("floatRange(0,1)(%q) = %v", v, err)
		}
	}
	for _, v := range []string{"-0.1", "1.1", "hot"} {
		if err := check(v); err == nil {
			t.Errorf("floatRange(0,1)(%q) = nil, want error", v)
		}
	}
}

func TestFloatMin(t *testing.T) {
	check := floatMin(0)
	if err := check("0"); err != nil {
		t.Errorf("floatMin(0)(\"0\") = %v", err)
	}
	if err := check("12.5"); err != nil {
		t.Errorf("floatMin(0)(\"12.5\") = %v", err)
	}
	for _, v := range []string{"-0.5", "many"} {
		if err := check(v); err == nil {
			t.Errorf("floatMin(0)(%q) = nil, want error", v)
		}
	}
}

// intMin must reject fractions: the target field is a whole token count.
func TestIntMin(t *testing.T) {
	check := intMin(1000)
	for _, v := range []string{"1000", "4096", " 2048 ", ""} {
		if err := check(v); err != nil {
			t.Errorf("intMin(1000)(%q) = %v", v, err)
		}
	}
	for _, v := range []string{"999", "1.5", "lots"} {
		if err := check(v); err == nil {
			t.Errorf("intMin(1000)(%q) = nil, want error", v)
		}
	}
}

// Cancel must stop the install. Nothing downstream reads the answer, so
// without this the acknowledgement is decoration.
func TestAcknowledgeTerraform(t *testing.T) {
	if err := acknowledgeTerraform(true); err != nil {
		t.Errorf("acknowledged but rejected: %v", err)
	}
	err := acknowledgeTerraform(false)
	if err == nil {
		t.Fatal("declining the BUSL-1.1 licence was accepted")
	}
	// The message has to say how to get out of the prompt, or the user is stuck.
	for _, want := range []string{"BUSL-1.1", "OpenTofu"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("message %q does not mention %q", err, want)
		}
	}
}
