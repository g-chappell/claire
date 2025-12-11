import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import App from "./App";
import "./index.css";

// pages
import CreateRun from "./pages/CreateRun";
import ChatPage from "./pages/ChatPage";
import PlanManageRun from "./pages/PlanManageRun";
import PlanGenerate from "./pages/PlanGenerate";
import PlanView from "./pages/PlanView";
import ImplementCodePage from "./pages/ImplementCode";
import RetrospectivePage from "./pages/Retrospective";
import SettingsPage from "./pages/SettingsPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: "plan/create", element: <CreateRun />},
      { path: "chat", element: <ChatPage /> },
      { path: "plan/manage", element: <PlanManageRun /> },
      { path: "plan/generate", element: <PlanGenerate /> },
      { path: "plan/view", element: <PlanView /> },
      { path: "implement", element: <ImplementCodePage /> },
      { path: "retrospective", element: <RetrospectivePage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><RouterProvider router={router} /></React.StrictMode>
);
