import { fileURLToPath, URL } from "node:url";
import { defineConfig, transformWithOxc } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    {
      name: "kuryos-js-as-jsx",
      enforce: "pre",
      async transform(code, id) {
        if (!/\/src\/.*\.js$/.test(id.replaceAll("\\", "/"))) return null;
        return transformWithOxc(code, id, { lang: "jsx", sourceType: "module" });
      },
    },
    react({ include: /\.[jt]sx?$/ }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  optimizeDeps: {
    rolldownOptions: {
      moduleTypes: { ".js": "jsx" },
    },
  },
  build: { outDir: "build" },
  test: { globals: true },
  server: { host: "0.0.0.0", port: 3000 },
  preview: { host: "0.0.0.0", port: 3000 },
});
