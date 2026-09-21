// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Timestamp and duration formatting for the whole client.
 *
 * Every view renders dates day-first (`dd.mm.yyyy`) in the browser's local
 * zone. These lived beside their callers until four near-identical copies had
 * accumulated — in `SessionData`, `SessionsTable` and `SessionCard` — each
 * with its own zero-padding and its own answer for a missing timestamp.
 */

/** What every formatter renders when it has no timestamp to render. */
const PLACEHOLDER = "-";

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function datePart(d: Date): string {
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

function timePart(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** `dd.mm.yyyy` — for places that show a day but no clock time. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return PLACEHOLDER;
  return datePart(new Date(iso));
}

/** `dd.mm.yyyy, hh:mm` — the default wherever the time of day matters. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return PLACEHOLDER;
  const d = new Date(iso);
  return `${datePart(d)}, ${timePart(d)}`;
}

/**
 * Date and time as separate fields, the date with a two-digit year.
 *
 * The session timeline stacks the two on their own lines, so it needs them
 * apart rather than joined. `time` is empty — not `-` — when there is no
 * timestamp, so the placeholder shows up once instead of twice.
 */
export function formatDateParts(iso: string | null | undefined): {
  date: string;
  time: string;
} {
  if (!iso) return { date: PLACEHOLDER, time: "" };
  const d = new Date(iso);
  const yy = String(d.getFullYear()).slice(-2);
  return {
    date: `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${yy}`,
    time: timePart(d),
  };
}

/** Elapsed time as `45s` or `5m 59s`; `-` when the range runs backwards. */
export function formatDuration(startIso: string, endIso: string): string {
  const millis = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (millis < 0) return PLACEHOLDER;
  // Round to whole seconds *first*: splitting an unrounded value lets the
  // remainder round up to 60 while the minute count stays floored, which is
  // how 359.771 s rendered as "5m 60s".
  const total = Math.round(millis / 1000);
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}
