import React from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';

import App from './App';
import ChatPage from './pages/ChatPage';
import SettingsPage from './pages/SettingsPage';   // ⬅ name matches the file

const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { path: '/',        element: <ChatPage /> },
      { path: '/settings', element: <SettingsPage /> }
    ]
  }
]);

const container = document.getElementById('root')!;
createRoot(container).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
