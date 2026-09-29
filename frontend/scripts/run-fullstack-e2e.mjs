import { spawn } from "node:child_process";
import { rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const playwrightCli = fileURLToPath(
  new URL("../node_modules/@playwright/test/cli.js", import.meta.url),
);
const child = spawn(
  process.execPath,
  [
    playwrightCli,
    "test",
    "--config",
    "playwright.fullstack.config.ts",
    ...process.argv.slice(2),
  ],
  { cwd: fileURLToPath(new URL("..", import.meta.url)), stdio: "inherit" },
);
const exitCode = await new Promise((resolve, reject) => {
  child.once("error", reject);
  child.once("exit", (code) => resolve(code ?? 1));
});
await rm(join(tmpdir(), "transit2gpx-fullstack-e2e"), {
  force: true,
  maxRetries: 5,
  recursive: true,
  retryDelay: 200,
});
process.exitCode = exitCode;
