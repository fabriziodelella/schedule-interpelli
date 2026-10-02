/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Proprietario (utente/organizzazione) del repository GitHub */
  readonly VITE_GH_OWNER?: string;
  /** Nome del repository GitHub */
  readonly VITE_GH_REPO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
