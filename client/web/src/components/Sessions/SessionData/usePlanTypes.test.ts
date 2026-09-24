// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { makeRound } from "@/test/factories";
import type { RoundDetail, TerraformPlanRef } from "@/types/api";
import { usePlanTypes } from "./usePlanTypes";

const STORAGE = "https://storage.test";

function planRef(id: number, name: string): TerraformPlanRef {
  return {
    id,
    url: `${STORAGE}/${name}`,
    content_type: "text/plain",
    file_size_bytes: 10,
    created_at: "2026-01-01T00:00:00Z",
    targets: [],
  };
}

/** A store answering a ranged read: 206, one byte, full metadata headers. */
function servePlan(name: string, type: string | null) {
  return http.get(`${STORAGE}/${name}`, () =>
    HttpResponse.text("p", {
      status: 206,
      headers: type ? { "x-amz-meta-type": type } : {},
    }),
  );
}

function rounds(plans: TerraformPlanRef[]): RoundDetail[] {
  return [makeRound({ plans })];
}

describe("usePlanTypes", () => {
  it("resolves every plan's flavour from its object metadata", async () => {
    server.use(servePlan("drift.txt", "drift"), servePlan("plan.txt", "plan"));

    const { result } = renderHook(() =>
      usePlanTypes(rounds([planRef(1, "drift.txt"), planRef(2, "plan.txt")])),
    );

    await waitFor(() => expect(result.current.get(1)).toBe("drift"));
    expect(result.current.get(2)).toBe("plan");
  });

  it("leaves a plan unresolved when the store exposes no flavour", async () => {
    // A proxy that drops `Access-Control-Expose-Headers`, or an object
    // stored before the backend wrote the metadata. The row keeps the
    // neutral label rather than guessing.
    server.use(servePlan("old.txt", null));

    const { result } = renderHook(() =>
      usePlanTypes(rounds([planRef(3, "old.txt")])),
    );

    await waitFor(() => expect(result.current.get(3)).toBeUndefined());
  });

  it("fetches each plan once across re-renders", async () => {
    // Polling re-renders the panel with a fresh `rounds` array and fresh
    // presigned URLs; neither may re-trigger the read.
    let hits = 0;
    server.use(
      http.get(`${STORAGE}/plan.txt`, () => {
        hits += 1;
        return HttpResponse.text("p", {
          status: 206,
          headers: { "x-amz-meta-type": "plan" },
        });
      }),
    );

    const { result, rerender } = renderHook(
      (props: { rounds: RoundDetail[] }) => usePlanTypes(props.rounds),
      { initialProps: { rounds: rounds([planRef(4, "plan.txt")]) } },
    );

    await waitFor(() => expect(result.current.get(4)).toBe("plan"));
    rerender({ rounds: rounds([planRef(4, "plan.txt")]) });
    await waitFor(() => expect(result.current.get(4)).toBe("plan"));

    expect(hits).toBe(1);
  });

  it("never has more than a handful of reads in flight", async () => {
    // A long session holds one plan per validation iteration. Labelling
    // them must not open a connection per plan.
    let inFlight = 0;
    let peak = 0;
    server.use(
      http.get(`${STORAGE}/:name`, async () => {
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        await new Promise((r) => setTimeout(r, 5));
        inFlight -= 1;
        return HttpResponse.text("p", {
          status: 206,
          headers: { "x-amz-meta-type": "plan" },
        });
      }),
    );

    const plans = Array.from({ length: 30 }, (_, i) =>
      planRef(100 + i, `p${i}.txt`),
    );
    const { result } = renderHook(() => usePlanTypes(rounds(plans)));

    await waitFor(() => expect(result.current.get(129)).toBe("plan"));
    expect(peak).toBeLessThanOrEqual(6);
  });

  it("accepts a flavour that arrived with a downloaded body", async () => {
    // `record` is how the opened-artifact panel hands back the metadata
    // its content fetch already carried — no second request for it.
    server.use(servePlan("late.txt", null));

    const { result } = renderHook(() =>
      usePlanTypes(rounds([planRef(5, "late.txt")])),
    );

    await waitFor(() => expect(result.current.get(5)).toBeUndefined());
    act(() => result.current.record(5, "drift"));

    expect(result.current.get(5)).toBe("drift");
  });
});
