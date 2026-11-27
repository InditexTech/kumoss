// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

package tui

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

// required is the validator for a field the stack cannot start without. The
// word matches the title suffix, so the error repeats what the user read.
func required(v string) error {
	if strings.TrimSpace(v) == "" {
		return errors.New("required")
	}
	return nil
}

// optionalMappingPrefix validates MAPPING_PREFIX_IDENTIFIER the way the
// mapping service does at startup, so a bad prefix fails here instead of in a
// crash-looping container. Empty is valid: only full URLs resolve then.
func optionalMappingPrefix(v string) error {
	raw := strings.TrimSpace(v)
	if raw == "" {
		return nil
	}
	u, err := url.Parse(raw)
	if err != nil {
		return errors.New("not a URL")
	}
	switch {
	case u.Scheme != "https" || u.Host == "":
		return errors.New("must be https:// with a host, e.g. https://github.com/my-org/")
	case u.User != nil:
		return errors.New("must not embed a password or token")
	case strings.ContainsAny(raw, "?#"):
		return errors.New("must not carry a query or fragment")
	}
	return nil
}

// Compacts a pasted service-account key onto one line: the .env format gives a
// variable one line, so pretty-printed JSON would land as several broken ones.
// Terraform, which reads GOOGLE_CREDENTIALS, accepts the compact form.
func jsonKey(v string) error {
	raw := strings.TrimSpace(v)
	if raw == "" {
		return errors.New("required")
	}
	var buf bytes.Buffer
	if err := json.Compact(&buf, []byte(raw)); err != nil {
		return errors.New("not a JSON key: paste the whole service-account file")
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

// floatRange accepts a number in [min, max], or blank — which is how the
// optional LLM knobs say "keep the repo's value".
func floatRange(min, max float64) func(string) error {
	return func(v string) error {
		if strings.TrimSpace(v) == "" {
			return nil
		}
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

// floatMin accepts a number >= min, or blank (see floatRange).
func floatMin(min float64) func(string) error {
	return func(v string) error {
		if strings.TrimSpace(v) == "" {
			return nil
		}
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

// intMin accepts a whole number >= min, or blank (see floatRange).
func intMin(min int) func(string) error {
	return func(v string) error {
		if strings.TrimSpace(v) == "" {
			return nil
		}
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

// azureAccount accepts an Azure storage account name: 3-24 lowercase letters
// and digits, as the portal enforces.
func azureAccount(v string) error {
	if !azureAccountPattern.MatchString(strings.TrimSpace(v)) {
		return errors.New("3-24 lowercase letters and digits")
	}
	return nil
}

var azureAccountPattern = regexp.MustCompile(`^[a-z0-9]{3,24}$`)

// minLen rejects a value shorter than n characters, after trimming: the
// RustFS entrypoint trims before the binary sees it, so padding is not length.
func minLen(n int, why string) func(string) error {
	return func(v string) error {
		if len([]rune(strings.TrimSpace(v))) < n {
			return fmt.Errorf("at least %d characters: %s", n, why)
		}
		return nil
	}
}
