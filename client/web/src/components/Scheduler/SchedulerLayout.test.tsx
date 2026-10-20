// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/render";
import type { OperationRole } from "@/types/api";
import type {
  Schedule,
  ScheduleOperation,
  UpdateScheduleRequest,
  CreateScheduleRequest,
} from "@/types/api_scheduler";
import SchedulerPage from "@/pages/SchedulerPage";
import SchedulerLayout from "./SchedulerLayout";

const auth = vi.hoisted(() => ({ operationRole: "devops" as OperationRole | null }));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ operationRole: auth.operationRole }),
}));

const nightly: Schedule = {
  uuid: "sched-1",
  owner_email: "owner@example.com",
  name: "nightly drift",
  kind: "drift",
  cron: "0 3 * * *",
  enabled: true,
  params: {
    repo_uri: "https://github.com/org/repo",
    terraform_providers: "azure",
    scope_id: "sub-1",
    q: "detect drift",
    is_partial: true,
  },
  next_run_at: "2026-10-20T03:00:00Z",
  last_run_at: null,
  created_at: "2026-10-01T00:00:00Z",
};

const failedRun: ScheduleOperation = {
  uuid: "op-1",
  session_uuid: "sess-1",
  schedule_uuid: "sched-1",
  kind: "drift",
  status: "failed",
  params: {},
  scheduled_at: "2026-10-19T03:00:00Z",
  started_at: null,
  finished_at: null,
  error: "runner failed: boom",
  created_at: "2026-10-19T03:00:00Z",
};

interface Calls {
  lists: URLSearchParams[];
  creates: CreateScheduleRequest[];
  updates: UpdateScheduleRequest[];
  deletes: string[];
}

function mockApi(): Calls {
  const calls: Calls = { lists: [], creates: [], updates: [], deletes: [] };
  server.use(
    http.get("/api/v1/schedules", ({ request }) => {
      calls.lists.push(new URL(request.url).searchParams);
      return HttpResponse.json({ items: [nightly], total: 1, page: 1, page_size: 10 });
    }),
    http.get("/api/v1/schedules/:id", () => HttpResponse.json(nightly)),
    http.post("/api/v1/schedules", async ({ request }) => {
      const body = (await request.json()) as CreateScheduleRequest;
      calls.creates.push(body);
      return HttpResponse.json({ ...nightly, ...body, uuid: "sched-2" }, { status: 201 });
    }),
    http.patch("/api/v1/schedules/:id", async ({ request }) => {
      const body = (await request.json()) as UpdateScheduleRequest;
      calls.updates.push(body);
      return HttpResponse.json({ ...nightly, ...body });
    }),
    http.delete("/api/v1/schedules/:id", ({ params }) => {
      calls.deletes.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("/api/v1/operations", () =>
      HttpResponse.json({ items: [failedRun], total: 1, page: 1, page_size: 50 }),
    ),
  );
  return calls;
}

function renderScheduler(path = "/scheduler") {
  return renderWithProviders(<SchedulerLayout />, {
    withNotifications: true,
    routerProps: { initialEntries: [path] },
  });
}

/** Comboboxes of the open form sheet (the toolbar has its own KIND filter). */
function formCombos() {
  const sheet = screen.getByLabelText(/^Name/).closest("[data-detail-content]");
  if (!(sheet instanceof HTMLElement)) throw new Error("no form sheet");
  return within(sheet).getAllByRole("combobox");
}

async function openDetail() {
  const user = userEvent.setup();
  renderScheduler();
  await user.click(await screen.findByText("nightly drift"));
  await screen.findByText("runner failed: boom");
  return user;
}

beforeEach(() => {
  auth.operationRole = "devops";
});

describe("SchedulerLayout access", () => {
  it("asks for an operation role when the caller has none", () => {
    auth.operationRole = null;
    renderScheduler();
    expect(
      screen.getByText("You need an operation role to access the scheduler."),
    ).toBeInTheDocument();
  });

  it("is reachable through the lazy scheduler page", async () => {
    mockApi();
    renderWithProviders(<SchedulerPage />, {
      withNotifications: true,
      routerProps: { initialEntries: ["/scheduler"] },
    });
    expect(await screen.findByText("nightly drift")).toBeInTheDocument();
  });
});

describe("SchedulerLayout list", () => {
  it("forwards the kind filter to the API", async () => {
    const calls = mockApi();
    renderScheduler("/scheduler?kind=import");
    await screen.findByText("nightly drift");
    expect(calls.lists[calls.lists.length - 1]?.get("kind")).toBe("import");
  });

  it("shows a schedule's details and its run history", async () => {
    mockApi();
    await openDetail();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("0 3 * * *").length).toBeGreaterThan(0);
  });

  it("closes the detail when the schedule can't be loaded", async () => {
    mockApi();
    server.use(
      http.get("/api/v1/schedules/:id", () =>
        HttpResponse.json({ detail: "gone" }, { status: 404 }),
      ),
    );
    const user = userEvent.setup();
    renderScheduler();
    await user.click(await screen.findByText("nightly drift"));
    expect(await screen.findByText(/Failed to load schedule/)).toBeInTheDocument();
  });
});

describe("SchedulerLayout editing", () => {
  it("updates only what changed and keeps params the form doesn't show", async () => {
    const calls = mockApi();
    const user = await openDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const name = screen.getByLabelText(/^Name/);
    await user.clear(name);
    await user.type(name, "weekly drift");
    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => expect(calls.updates).toHaveLength(1));
    expect(calls.updates[0]).toEqual({ name: "weekly drift" });
    expect(await screen.findByText("Schedule updated")).toBeInTheDocument();
  });

  it("sends the merged params when a field changes", async () => {
    const calls = mockApi();
    const user = await openDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));

    await user.type(screen.getByLabelText(/^IaC Path/), "infra");
    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => expect(calls.updates).toHaveLength(1));
    expect(calls.updates[0].params).toEqual({ ...nightly.params, iac_path: "infra" });
  });

  it("does not let the kind of an existing schedule change", async () => {
    mockApi();
    const user = await openDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const [kind] = formCombos();
    expect(kind).toHaveAttribute("aria-disabled", "true");
  });

  it("reports a failed save", async () => {
    mockApi();
    server.use(
      http.patch("/api/v1/schedules/:id", () =>
        HttpResponse.json({ detail: "Invalid cron expression" }, { status: 422 }),
      ),
    );
    const user = await openDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const cron = screen.getByLabelText(/^Cron Expression/);
    await user.clear(cron);
    await user.type(cron, "0 0 31 2 *");
    await user.click(screen.getByRole("button", { name: "Update" }));
    expect(await screen.findByText(/Failed to save schedule/)).toBeInTheDocument();
  });

  it("deletes a schedule", async () => {
    const calls = mockApi();
    const user = await openDetail();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.deletes).toEqual(["sched-1"]));
    expect(await screen.findByText("Schedule deleted")).toBeInTheDocument();
  });

  it("reports a failed delete", async () => {
    mockApi();
    server.use(
      http.delete("/api/v1/schedules/:id", () =>
        HttpResponse.json({ detail: "nope" }, { status: 403 }),
      ),
    );
    const user = await openDetail();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText(/Failed to delete schedule/)).toBeInTheDocument();
  });
});

describe("SchedulerLayout creating", () => {
  async function fillForm(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText(/^Name/), "import nightly");
    await user.type(screen.getByLabelText(/^Cron Expression/), "0 2 * * *");
    await user.type(screen.getByLabelText(/^Repository URI/), "https://github.com/org/repo");
    await user.type(screen.getByLabelText(/^Query/), "import everything");
    await user.type(screen.getByLabelText(/^Scope ID/), "sub-9");
    const [, provider] = formCombos();
    await user.click(provider);
    await user.click(within(screen.getByRole("listbox")).getByRole("option", { name: "GCP" }));
  }

  it("creates a schedule from the form", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    renderScheduler();
    await user.click(await screen.findByRole("button", { name: "New Schedule" }));

    const [kind] = formCombos();
    await user.click(kind);
    await user.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Import" }));
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls.creates).toHaveLength(1));
    expect(calls.creates[0]).toEqual({
      name: "import nightly",
      kind: "import",
      cron: "0 2 * * *",
      enabled: true,
      params: {
        repo_uri: "https://github.com/org/repo",
        terraform_providers: "gcp",
        q: "import everything",
        scope_id: "sub-9",
      },
    });
    expect(await screen.findByText("Schedule created")).toBeInTheDocument();
  });

  it("does not submit an incomplete form", async () => {
    const calls = mockApi();
    const user = userEvent.setup();
    renderScheduler();
    await user.click(await screen.findByRole("button", { name: "New Schedule" }));
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(calls.creates).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Create" })).not.toBeInTheDocument();
  });

  it("defaults developers to import and blocks drift", async () => {
    auth.operationRole = "developer";
    mockApi();
    const user = userEvent.setup();
    renderScheduler();
    await user.click(await screen.findByRole("button", { name: "New Schedule" }));
    const [kind] = formCombos();
    expect(kind).toHaveTextContent("Import");
    await user.click(kind);
    expect(
      within(screen.getByRole("listbox")).getByRole("option", { name: "Drift" }),
    ).toHaveAttribute("aria-disabled", "true");
  });
});
