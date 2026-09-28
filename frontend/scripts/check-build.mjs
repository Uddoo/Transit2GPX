import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";

const frontendDir = resolve(import.meta.dirname, "..");
const manifestPath = resolve(frontendDir, "dist", ".vite", "manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const expectedRoutes = [
  "src/features/csv-import/CsvImportPage.tsx",
  "src/features/data-settings/DataSettingsPage.tsx",
  "src/features/export/ExportPage.tsx",
  "src/features/journey-editor/JourneyEditorPage.tsx",
  "src/features/journeys/JourneysPage.tsx",
];
const entry = manifest["index.html"];
if (!entry?.isEntry) {
  throw new Error("Vite manifest is missing the main entry");
}
for (const route of expectedRoutes) {
  // Shared code in a dynamic entry can make Rollup use a chunk key instead
  // of the source path. Still require that exact route to be a lazy entry.
  const routeName = route.split("/").at(-1).replace(/\.tsx$/, "");
  const routeKey = entry.dynamicImports?.find(
    (key) => key === route || manifest[key]?.name === routeName,
  );
  if (!routeKey || !manifest[routeKey]?.isDynamicEntry) {
    throw new Error(`Route is not emitted as a lazy chunk: ${route}`);
  }
}
const entryBytes = (await stat(resolve(frontendDir, "dist", entry.file))).size;
if (entryBytes > 350_000) {
  throw new Error(`Main entry exceeds the 350 kB lazy-loading budget: ${entryBytes}`);
}
console.log(
  `Verified ${expectedRoutes.length} lazy route chunks; main entry is ${entryBytes} bytes`,
);
