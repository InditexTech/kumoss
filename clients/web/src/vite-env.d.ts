/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOCK_USER_EMAIL: string;
  readonly VITE_MOCK_API: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
