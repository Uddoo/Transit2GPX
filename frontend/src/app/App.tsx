import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./AppShell";
import { CsvImportPage } from "../features/csv-import/CsvImportPage";
import { DataSettingsPage } from "../features/data-settings/DataSettingsPage";
import { ExportPage } from "../features/export/ExportPage";
import { JourneyEditorPage } from "../features/journey-editor/JourneyEditorPage";
import { JourneysPage } from "../features/journeys/JourneysPage";

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

