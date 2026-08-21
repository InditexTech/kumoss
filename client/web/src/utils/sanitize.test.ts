// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import { sanitizeHtml, containsHtml, isAllowedUrl } from './sanitize';

describe('sanitizeHtml', () => {
  it('keeps allowed tags', () => {
    expect(sanitizeHtml('<b>bold</b>')).toBe('<b>bold</b>');
    expect(sanitizeHtml('<em>italic</em>')).toBe('<em>italic</em>');
  });

  it('strips disallowed tags', () => {
    expect(sanitizeHtml('<script>alert(1)</script>')).toBe('');
    expect(sanitizeHtml('<img src=x onerror=alert(1)>')).toBe('');
    expect(sanitizeHtml('<a href="http://evil.com">click</a>')).toBe('click');
  });

  it('strips all attributes', () => {
    expect(sanitizeHtml('<b class="x" style="color:red">text</b>')).toBe('<b>text</b>');
  });

  it('handles empty and plain text', () => {
    expect(sanitizeHtml('')).toBe('');
    expect(sanitizeHtml('plain text')).toBe('plain text');
  });
});

describe('containsHtml', () => {
  it('returns false for plain text', () => {
    expect(containsHtml('plain text')).toBe(false);
    expect(containsHtml('hello world')).toBe(false);
    expect(containsHtml('')).toBe(false);
  });

  it('returns true for script tags', () => {
    expect(containsHtml('<script>alert(1)</script>')).toBe(true);
  });

  it('returns true for img tags', () => {
    expect(containsHtml('<img src=x onerror=alert(1)>')).toBe(true);
  });

  it('returns true for anchor tags', () => {
    expect(containsHtml('<a href="http://evil.com">click</a>')).toBe(true);
  });

  it('returns true for text with angle brackets that DOMPurify interprets as markup', () => {
    expect(containsHtml('5 > 3 and 2 < 4')).toBe(true);
  });
});

describe('isAllowedUrl', () => {
  it('accepts allowed HTTPS domains', () => {
    expect(isAllowedUrl('https://dev.azure.com/org/project')).toBe(true);
    expect(isAllowedUrl('https://portal.azure.com/#blade/resource')).toBe(true);
    expect(isAllowedUrl('https://console.cloud.google.com/home')).toBe(true);
    expect(isAllowedUrl('https://teams.microsoft.com/channel')).toBe(true);
    expect(isAllowedUrl('https://github.com/org/repo/pull/5')).toBe(true);
  });

  it('accepts subdomains of allowed domains', () => {
    expect(isAllowedUrl('https://sub.dev.azure.com/path')).toBe(true);
  });

  it('rejects HTTP', () => {
    expect(isAllowedUrl('http://dev.azure.com/org')).toBe(false);
  });

  it('rejects disallowed domains', () => {
    expect(isAllowedUrl('https://evil.com/phish')).toBe(false);
    expect(isAllowedUrl('https://notazure.com')).toBe(false);
  });

  it('rejects invalid URLs', () => {
    expect(isAllowedUrl('not-a-url')).toBe(false);
    expect(isAllowedUrl('')).toBe(false);
  });

  it('rejects javascript: protocol', () => {
    expect(isAllowedUrl('javascript:alert(1)')).toBe(false);
  });
});
