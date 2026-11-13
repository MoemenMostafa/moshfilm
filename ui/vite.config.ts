/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const target = "http://127.0.0.1:5717";

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "../src/moshfilm/static",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: "index.html",
        render: "render.html",
      },
    },
  },
  server: {
    proxy: {
      "/api": { target, changeOrigin: true },
      "/film": { target, changeOrigin: true },
    },
  },
  test: { environment: "jsdom" },
});
