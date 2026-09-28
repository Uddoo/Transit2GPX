import { Navigate, Route, Routes } from "react-router-dom";
import { lazy } from "react";

import { AppShell } from "./AppShell";
const CsvImportPage = lazy(() => import("../features/csv-import/CsvImportPage").then((module) => ({ default: module.CsvImportPage })));
const DataSettingsPage = lazy(() => import("../features/data-settings/DataSettingsPage").then((module) => ({ default: module.DataSettingsPage })));
const ExportPage = lazy(() => import("../features/export/ExportPage").then((module) => ({ default: module.ExportPage })));
const JourneyEditorPage = lazy(() => import("../features/journey-editor/JourneyEditorPage").then((module) => ({ default: module.JourneyEditorPage })));
const JourneysPage = lazy(() => import("../features/journeys/JourneysPage").then((module) => ({ default: module.JourneysPage })));

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/journeys/new" />} />
        <Route path="/journeys" element={<JourneysPage />} />
        <Route path="/journeys/new" element={<JourneyEditorPage />} />
        <Route path="/imports/csv" element={<CsvImportPage />} />
        <Route path="/exports" element={<ExportPage />} />
        <Route path="/settings/data" element={<DataSettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate replace to="/journeys/new" />} />
    </Routes>
  );
}
