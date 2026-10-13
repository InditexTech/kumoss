// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchPlanType } from "@/services/core/sessions";
import type { PlanType, RoundDetail } from "@/types/api";

/**
 * Resolved plan flavours, plus a way to contribute one.
 *
 * `record` exists because the metadata rides along with the body: a
 * panel that downloads a plan already holds its flavour, and handing it
 * back here keeps the answer where everything else reads it instead of
 * letting it die with the component.
 */
export interface PlanTypes {
  get(id: number): PlanType | undefined;
  record(id: number, type: PlanType): void;
}

/**
 * The most flavour reads to keep open at once. Labels are decoration: they
 * must not saturate the browser's connection pool and delay the artifact
 * the user actually clicked.
 */
const MAX_IN_FLIGHT = 6;

/** Map `items` through `fn`, at most `limit` at a time, in input order. */
async function mapBounded<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      for (let i = next++; i < items.length; i = next++) {
        out[i] = await fn(items[i]);
      }
    }),
  );
  return out;
}

/**
 * Plan flavours for a session's rounds, keyed by plan id.
 *
 * The flavour is object metadata, not payload, so each plan costs one ranged
 * request (see `fetchPlanType`) — the price of keeping it out of the
 * database, paid because the timeline labels rows before anything is opened.
 *
 * Keyed by `id`, never by `url`: presigned URLs carry a fresh signature on
 * every read-model fetch, so a URL-keyed cache would miss on every poll and
 * refetch the whole timeline's plans.
 *
 * `requested` is a ref, not state: it must be updated synchronously as the
 * effect dispatches, or a second render arriving mid-flight would queue the
 * same fetches again. Ids land in it before their response does, so a failed
 * read is not retried — the row keeps the neutral label until something
 * opens the plan and calls `record`.
 */
export function usePlanTypes(rounds: RoundDetail[]): PlanTypes {
  const [types, setTypes] = useState<ReadonlyMap<number, PlanType>>(new Map());
  const requested = useRef<Set<number>>(new Set());

  // Flattened here so the effect depends on the plans themselves rather
  // than on `rounds`, whose identity changes on every poll.
  const plans = useMemo(() => rounds.flatMap((r) => r.plans), [rounds]);

  useEffect(() => {
    const pending = plans.filter((p) => !requested.current.has(p.id));
    if (pending.length === 0) return;
    for (const plan of pending) requested.current.add(plan.id);

    let cancelled = false;
    void (async () => {
      const found = await mapBounded(
        pending,
        MAX_IN_FLIGHT,
        async (plan) => [plan.id, await fetchPlanType(plan.url)] as const,
      );
      if (cancelled) return;
      setTypes((prev) => {
        const resolved = found.filter(
          (entry): entry is readonly [number, PlanType] => entry[1] !== null,
        );
        // Every read came back unreadable: a new Map here would change
        // identity and re-render the panel for no new information.
        if (resolved.length === 0) return prev;
        const next = new Map(prev);
        for (const [id, type] of resolved) next.set(id, type);
        return next;
      });
    })();

    return () => {
      cancelled = true;
    };
  }, [plans]);

  const record = useCallback((id: number, type: PlanType) => {
    // Marked as requested too: a flavour that arrived with a body is as
    // good as one the effect fetched, and the ranged read would only
    // confirm it.
    requested.current.add(id);
    setTypes((prev) =>
      prev.get(id) === type ? prev : new Map(prev).set(id, type),
    );
  }, []);

  return useMemo(
    () => ({ get: (id: number) => types.get(id), record }),
    [types, record],
  );
}
