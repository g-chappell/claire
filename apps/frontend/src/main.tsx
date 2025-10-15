// src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import App from "./App";
import "./index.css";

import ChatPage from "./pages/ChatPage";
import SettingsPage from "./pages/SettingsPage";
import PlanPage from "./pages/PlanPage";
import ImplementPage from "./pages/ImplementPage";
import ReviewPage from "./pages/ReviewPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: "chat", element: <ChatPage /> },
      { path: "plan", element: <PlanPage /> },
      { path: "implement", element: <ImplementPage /> },
      { path: "review", element: <ReviewPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
