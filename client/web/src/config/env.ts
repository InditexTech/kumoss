// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

type EnvKey = keyof ImportMetaEnv;

const runtimeEnv = (window as unknown as Record<string, unknown>).__ENV__ as
  | Record<string, string>
  | undefined;

function getEnv(key: EnvKey): string {
  return runtimeEnv?.[key] ?? import.meta.env[key] ?? "";
}

export const env = {
  VITE_MOCK_API: getEnv("VITE_MOCK_API"),
};
