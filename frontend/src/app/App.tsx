import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./AppShell";

const CsvImportPage = lazy(() =>
  import("../features/csv-import/CsvImportPage").then((module) => ({
    default: module.CsvImportPage,
  })),
);
const DataSettingsPage = lazy(() =>
  import("../features/data-settings/DataSettingsPage").then((module) => ({
    default: module.DataSettingsPage,
  })),
);
const ExportPage = lazy(() =>
  import("../features/export/ExportPage").then((module) => ({
    default: module.ExportPage,
  })),
);
const JourneyEditorPage = lazy(() =>
  import("../features/journey-editor/JourneyEditorPage").then((module) => ({
    default: module.JourneyEditorPage,
  })),
);
const JourneysPage = lazy(() =>
  import("../features/journeys/JourneysPage").then((module) => ({
    default: module.JourneysPage,
  })),
);

function LazyRoute({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <section className="simple-page" aria-busy="true" aria-live="polite">
          <p className="panel-message" role="status">
            正在加载页面…
          </p>
        </section>
      }
    >
      {children}
    </Suspense>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/journeys/new" />} />
        <Route
          path="/journeys"
          element={
            <LazyRoute>
              <JourneysPage />
            </LazyRoute>
          }
        />
        <Route
          path="/journeys/new"
          element={
            <LazyRoute>
              <JourneyEditorPage />
            </LazyRoute>
          }
        />
        <Route
          path="/imports/csv"
          element={
            <LazyRoute>
              <CsvImportPage />
            </LazyRoute>
          }
        />
        <Route
          path="/exports"
          element={
            <LazyRoute>
              <ExportPage />
            </LazyRoute>
          }
        />
        <Route
          path="/settings/data"
          element={
            <LazyRoute>
              <DataSettingsPage />
            </LazyRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate replace to="/journeys/new" />} />
    </Routes>
  );
}
