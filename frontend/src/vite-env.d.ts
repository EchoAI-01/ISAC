/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 跨源部署时的 API 基址 (默认空 = 同源, 经 Vite proxy / 反代)。 */
  readonly VITE_ISAC_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
