import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Nome del repo usato per il `base` quando VITE_GH_REPO non è impostata.
// Deve coincidere con il default in src/App.tsx.
const DEFAULT_REPO = "schedule-interpelli";

export default defineConfig(({ command, mode }) => {
  // loadEnv legge anche le variabili VITE_* presenti nell'ambiente (es. in Actions).
  const env = loadEnv(mode, ".", "VITE_");
  const repo = env.VITE_GH_REPO || DEFAULT_REPO;

  return {
    plugins: [react()],
    // GitHub Pages serve il sito su https://<owner>.github.io/<repo>/
    base: command === "build" ? `/${repo}/` : "/",
  };
});
