// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOCK_USER_EMAIL: string;
  readonly VITE_MOCK_API: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
