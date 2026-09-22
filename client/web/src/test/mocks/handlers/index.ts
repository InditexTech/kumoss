// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * One module per backend resource, mirroring `src/services/core/`.
 * Everything reads and writes `mockState`, which starts empty — tests
 * add exactly the sessions they need; the browser worker seeds a full
 * set (see `../seed.ts`).
 */

import { adminHandlers } from "./admin";
import { artifactHandlers } from "./artifacts";
import { authHandlers } from "./auth";
import { eventHandlers } from "./events";
import { iacActionHandlers } from "./iac_actions";
import { notificationHandlers } from "./notifications";
import { repositoryHandlers } from "./repository";
import { sessionHandlers } from "./sessions";
import { userHandlers } from "./users";

export const handlers = [
  ...authHandlers,
  ...userHandlers,
  ...sessionHandlers,
  ...adminHandlers,
  ...iacActionHandlers,
  ...eventHandlers,
  ...repositoryHandlers,
  ...notificationHandlers,
  ...artifactHandlers,
];
