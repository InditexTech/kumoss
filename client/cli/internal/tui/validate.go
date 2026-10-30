// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"errors"
	"strconv"
	"strings"
)

// required rejects an empty value.
func required(v string) error {
	if strings.TrimSpace(v) == "" {
		return errors.New("required")
	}
	return nil
}

// email is a loose check: enough to catch a typo, not an RFC 5322 parser.
func email(v string) error {
	at := strings.IndexByte(v, '@')
	if at < 1 || at == len(v)-1 || strings.ContainsAny(v, " \t") {
		return errors.New("enter a valid email")
	}
	return nil
}

// floatRange accepts a number in [min, max].
func floatRange(min, max float64) func(string) error {
	return func(v string) error {
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		if err != nil {
			return errors.New("enter a number")
		}
		if f < min || f > max {
			return errors.New("out of range")
		}
		return nil
	}
}

// floatMin accepts a number >= min.
func floatMin(min float64) func(string) error {
	return func(v string) error {
		f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		if err != nil {
			return errors.New("enter a number")
		}
		if f < min {
			return errors.New("must not be negative")
		}
		return nil
	}
}

// intMin accepts a whole number >= min.
func intMin(min int) func(string) error {
	return func(v string) error {
		n, err := strconv.Atoi(strings.TrimSpace(v))
		if err != nil {
			return errors.New("enter a whole number")
		}
		if n < min {
			return errors.New("must be at least " + strconv.Itoa(min))
		}
		return nil
	}
}
