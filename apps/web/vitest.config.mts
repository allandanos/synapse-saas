import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/* Unit tests for pure console logic (tour builder, config parsers).
 * Node environment: no DOM; JSX is compiled with the automatic runtime so
 * `.tsx` modules that build React elements import cleanly. */
export default defineConfig({
  // Vite 8 transforms with Oxc (`esbuild` is deprecated there).
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts?(x)"],
  },
});
