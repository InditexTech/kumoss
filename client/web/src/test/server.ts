// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { setupServer } from "msw/node";
import { sessionHandlers } from "./handlers";

export const server = setupServer(...sessionHandlers);
