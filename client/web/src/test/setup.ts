// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { server } from './server';
import { loadAuthConfig } from '@/services/auth';
import { beforeAll, afterEach, afterAll, vi } from 'vitest';

vi.mock("lottie-react", () => ({
  default: () => null,
  __esModule: true,
}));

Element.prototype.scrollIntoView = vi.fn();

beforeAll(async () => {
  server.listen({ onUnhandledRequest: 'error' });
  // main.tsx awaits this before root.render, so the suite should too:
  // metadataHeaderPrefix() then reads a loaded config, not its fallback.
  await loadAuthConfig();
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
