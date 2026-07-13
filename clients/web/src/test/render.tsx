// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, renderHook } from "@testing-library/react";
import type { RenderOptions, RenderHookOptions } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { MemoryRouterProps } from "react-router-dom";
import { SessionProvider } from "@/contexts/SessionContext";
import { ModeProvider } from "@/contexts/ModeContext";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { AssistantMsgProvider } from "@/contexts/AssistantMsgContext";

interface ProviderOptions {
  routerProps?: Omit<MemoryRouterProps, "children">;
  withNotifications?: boolean;
  withAssistantMsg?: boolean;
}

function buildWrapper({ routerProps, withNotifications, withAssistantMsg }: ProviderOptions = {}) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    let node = children;
    if (withAssistantMsg) node = React.createElement(AssistantMsgProvider, null, node);
    if (withNotifications) node = React.createElement(NotificationProvider, null, node);
    node = React.createElement(ModeProvider, null, node);
    node = React.createElement(SessionProvider, null, node);
    return React.createElement(
      MemoryRouter,
      { initialEntries: ["/home"], ...routerProps },
      node,
    );
  };
}

export function renderWithProviders(
  ui: React.ReactElement,
  options?: ProviderOptions & Omit<RenderOptions, "wrapper">,
) {
  const { routerProps, withNotifications, withAssistantMsg, ...renderOptions } = options ?? {};
  return render(ui, {
    wrapper: buildWrapper({ routerProps, withNotifications, withAssistantMsg }),
    ...renderOptions,
  });
}

export function createWrapper(options?: ProviderOptions) {
  return buildWrapper(options);
}

export function renderHookWithProviders<R>(
  hook: () => R,
  options?: ProviderOptions & Omit<RenderHookOptions<unknown>, "wrapper">,
) {
  const { routerProps, withNotifications, withAssistantMsg, ...hookOptions } = options ?? {};
  return renderHook(hook, {
    wrapper: buildWrapper({ routerProps, withNotifications, withAssistantMsg }),
    ...hookOptions,
  });
}
