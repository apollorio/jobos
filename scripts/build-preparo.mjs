import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const esbuild = createRequire("D:/dev/_dev web/__core.js/package.json")("esbuild");

await esbuild.build({
  entryPoints: [resolve(root, "web/painel/src/preparo.ts")],
  outfile: resolve(root, "web/painel/preparo.js"),
  bundle: true,
  format: "iife",
  globalName: "JobosPreparo",
  platform: "browser",
  target: "es2022",
  legalComments: "none",
  charset: "utf8",
});
