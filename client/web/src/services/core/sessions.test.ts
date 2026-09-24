// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { fetchArtifact, fetchPlanType } from "./sessions";

const STORAGE = "https://storage.test";

describe("fetchPlanType", () => {
  it("reads the flavour from the S3-style metadata header", async () => {
    server.use(
      http.get(`${STORAGE}/a.txt`, () =>
        HttpResponse.text("p", {
          status: 206,
          headers: { "x-amz-meta-type": "drift" },
        }),
      ),
    );

    expect(await fetchPlanType(`${STORAGE}/a.txt`)).toBe("drift");
  });

  it("reads the flavour from the Azure-style metadata header", async () => {
    // Azure Blob returns user metadata as `x-ms-meta-*`; the same object
    // written by the same backend call is unreadable via the S3 spelling.
    server.use(
      http.get(`${STORAGE}/b.txt`, () =>
        HttpResponse.text("p", {
          status: 206,
          headers: { "x-ms-meta-type": "drift" },
        }),
      ),
    );

    expect(await fetchPlanType(`${STORAGE}/b.txt`)).toBe("drift");
  });

  it("asks for a single byte so the body is never downloaded", async () => {
    let range: string | null = null;
    server.use(
      http.get(`${STORAGE}/c.txt`, ({ request }) => {
        range = request.headers.get("Range");
        return HttpResponse.text("p", {
          status: 206,
          headers: { "x-amz-meta-type": "plan" },
        });
      }),
    );

    await fetchPlanType(`${STORAGE}/c.txt`);

    expect(range).toBe("bytes=0-0");
  });

  it("returns null when the store answers with an error", async () => {
    server.use(
      http.get(
        `${STORAGE}/gone.txt`,
        () => new HttpResponse(null, { status: 404 }),
      ),
    );

    expect(await fetchPlanType(`${STORAGE}/gone.txt`)).toBeNull();
  });

  it("returns null when the request throws", async () => {
    // A CORS rejection or a dropped connection surfaces as a thrown
    // TypeError, not a response. The row keeps the neutral label.
    server.use(http.get(`${STORAGE}/boom.txt`, () => HttpResponse.error()));

    expect(await fetchPlanType(`${STORAGE}/boom.txt`)).toBeNull();
  });

  it("returns null for an unrecognised flavour", async () => {
    server.use(
      http.get(`${STORAGE}/weird.txt`, () =>
        HttpResponse.text("p", {
          status: 206,
          headers: { "x-amz-meta-type": "something-else" },
        }),
      ),
    );

    expect(await fetchPlanType(`${STORAGE}/weird.txt`)).toBeNull();
  });
});

describe("fetchArtifact", () => {
  it("returns the body and the flavour from one response", async () => {
    server.use(
      http.get(`${STORAGE}/plan.txt`, () =>
        HttpResponse.text("plan body", {
          headers: { "x-amz-meta-type": "plan" },
        }),
      ),
    );

    expect(await fetchArtifact(`${STORAGE}/plan.txt`)).toEqual({
      text: "plan body",
      planType: "plan",
    });
  });

  it("throws when the store rejects the read", async () => {
    server.use(
      http.get(
        `${STORAGE}/nope.txt`,
        () => new HttpResponse(null, { status: 403 }),
      ),
    );

    await expect(fetchArtifact(`${STORAGE}/nope.txt`)).rejects.toThrow(
      "Failed to fetch artifact: 403",
    );
  });
});
