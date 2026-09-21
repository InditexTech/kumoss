// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { setupServer } from "msw/node";
// "./handlers" resolves to the superseded `handlers.ts`, not this
// directory's `index.ts` — the same trap `browser.ts` documents.
import { handlers } from "./handlers/index";

export const server = setupServer(...handlers);
