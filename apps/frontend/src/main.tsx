import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import App from "./App";
import "./index.css";

// pages
import ChatPage from "./pages/ChatPage";
import SettingsPage from "./pages/SettingsPage";
import PlanManageRun from "./pages/PlanManageRun";
import PlanGenerate from "./pages/PlanGenerate";
import PlanView from "./pages/PlanView";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: "chat", element: <ChatPage /> },
      { path: "plan/manage", element: <PlanManageRun /> },
      { path: "plan/generate", element: <PlanGenerate /> },
      { path: "plan/view", element: <PlanView /> },
      { path: "implement", element: <div className="p-6 opacity-60">Implement (coming soon)</div> },
      { path: "review", element: <div className="p-6 opacity-60">Review (coming soon)</div> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><RouterProvider router={router} /></React.StrictMode>
);
