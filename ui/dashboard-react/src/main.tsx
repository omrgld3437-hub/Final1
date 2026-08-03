import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import { DashboardProvider } from "./context/DashboardContext.tsx";
import { AppErrorBoundary } from "./app/AppErrorBoundary.tsx";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <DashboardProvider>
        <App />
      </DashboardProvider>
    </AppErrorBoundary>
  </StrictMode>
);
