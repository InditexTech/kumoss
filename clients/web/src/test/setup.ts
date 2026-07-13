// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { server } from '../mocks/server';
import { beforeAll, afterEach, afterAll, vi } from 'vitest';

vi.mock("lottie-react", () => ({
  default: () => null,
  __esModule: true,
}));

Element.prototype.scrollIntoView = vi.fn();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
