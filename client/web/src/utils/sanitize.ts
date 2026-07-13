// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import DOMPurify from 'dompurify';

const ALLOWED_TAGS: string[] = ['b', 'i', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li'];

export function sanitizeHtml(dirty: string): string {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS,
    ALLOWED_ATTR: [],
  });
}

const ALLOWED_DOMAINS: string[] = [
  'dev.azure.com',
  'portal.azure.com',
  'console.cloud.google.com',
  'teams.microsoft.com',
];

export function containsHtml(text: string): boolean {
  const stripped = text.replace(/\s+/g, ' ').trim();
  const sanitized = DOMPurify.sanitize(stripped, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
  return sanitized !== stripped;
}

export function isAllowedUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return false;
    return ALLOWED_DOMAINS.some(
      (domain) =>
        parsed.hostname === domain || parsed.hostname.endsWith('.' + domain),
    );
  } catch {
    return false;
  }
}
