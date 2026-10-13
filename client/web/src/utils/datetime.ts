// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Timestamp and duration formatting for the whole client. Every view renders
 * dates day-first (`dd.mm.yyyy`) in the browser's local zone.
 */

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

/**
 * `null` for anything `Date` cannot parse, so callers reach the placeholder.
 * An absent timestamp and an unparseable one are the same thing to a reader,
 * and `new Date("garbage")` is an Invalid Date whose getters return `NaN`.
 */
function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** `dd.mm.yyyy` — for places that show a day but no clock time. */
export function formatDate(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? datePart(d) : PLACEHOLDER;
}

/** `dd.mm.yyyy, hh:mm` — the default wherever the time of day matters. */
export function formatDateTime(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? `${datePart(d)}, ${timePart(d)}` : PLACEHOLDER;
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
  const d = parse(iso);
  if (!d) return { date: PLACEHOLDER, time: "" };
  const yy = String(d.getFullYear()).slice(-2);
  return {
    date: `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${yy}`,
    time: timePart(d),
  };
}

/**
 * Elapsed time as `45s` or `5m 59s`; `-` when the range runs backwards or
 * either end is unparseable — `NaN < 0` is false, so an Invalid Date would
 * otherwise slip past the backwards check and render `NaNm NaNs`.
 */
export function formatDuration(startIso: string, endIso: string): string {
  const start = parse(startIso);
  const end = parse(endIso);
  if (!start || !end) return PLACEHOLDER;
  const millis = end.getTime() - start.getTime();
  if (millis < 0) return PLACEHOLDER;
  // Round to whole seconds *first*: splitting an unrounded value lets the
  // remainder round up to 60 while the minute count stays floored ("5m 60s").
  const total = Math.round(millis / 1000);
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}
