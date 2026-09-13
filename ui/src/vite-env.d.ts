/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PLANNER_ISSUER?: string;
  readonly VITE_UI_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
