import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import "./styles.css";
import { PrefsProvider } from "./lib/prefs";
import { Layout } from "./components/Layout";
import { Overview } from "./pages/Overview";
import { Activities } from "./pages/Activities";
import { ActivityDetail } from "./pages/ActivityDetail";
import { Recovery } from "./pages/Recovery";
import { Training } from "./pages/Training";
import { DataExplorer } from "./pages/DataExplorer";
import { Settings } from "./pages/Settings";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Overview /> },
      { path: "activities", element: <Activities /> },
      { path: "activities/:id", element: <ActivityDetail /> },
      { path: "recovery", element: <Recovery /> },
      { path: "training", element: <Training /> },
      { path: "explorer", element: <DataExplorer /> },
      { path: "settings", element: <Settings /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PrefsProvider>
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </PrefsProvider>
  </StrictMode>,
);
