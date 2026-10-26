import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import { TraceProvider } from "./components/Trace";
import Attribution from "./pages/Attribution";
import Audit from "./pages/Audit";
import Data from "./pages/Data";
import Funding from "./pages/Funding";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Reconciliation from "./pages/Reconciliation";
import Reports from "./pages/Reports";
import { SchemeProvider } from "./scheme";
import { ThemeProvider } from "./theme";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "./styles.css";

function Gate() {
  const { user, loading } = useAuth();
  if (loading) return <div className="loading full">Loading…</div>;
  if (!user) return <Login />;
  return (
    <SchemeProvider>
      <TraceProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="reconciliation" element={<Reconciliation />} />
            <Route path="attribution" element={<Attribution />} />
            <Route path="funding" element={<Funding />} />
            <Route path="reports" element={<Reports />} />
            <Route path="data" element={<Data />} />
            <Route path="audit" element={<Audit />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </TraceProvider>
    </SchemeProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);
