/** Routes. Chat at / and /c/:conversationId/t/:threadId; admin guarded by RequireAdmin (server enforces too). */
import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";
import { Spinner } from "../components/ui";
import { GuestOnly, LoginPage, RegisterPage, RequireAdmin, RequireAuth } from "../features/auth/AuthPages";
import { ChatPage } from "../features/chat/ChatPage";
import { AppLayout } from "../features/layout/AppLayout";

// Charts-heavy pages load on demand.
const HistoryPage = lazy(() => import("../features/history/HistoryPage"));
const UsagePage = lazy(() => import("../features/usage/UsagePage"));
const AdminPage = lazy(() => import("../features/admin/AdminPage"));

const page = (el: React.ReactNode) => (
  <Suspense fallback={<div className="flex h-full items-center justify-center"><Spinner className="h-6 w-6" /></div>}>{el}</Suspense>
);

export const router = createBrowserRouter([
  { path: "/login", element: <GuestOnly><LoginPage /></GuestOnly> },
  { path: "/register", element: <GuestOnly><RegisterPage /></GuestOnly> },
  {
    path: "/",
    element: <RequireAuth><AppLayout /></RequireAuth>,
    children: [
      { index: true, element: <ChatPage /> },
      { path: "c/:conversationId", element: <ChatPage /> },
      { path: "c/:conversationId/t/:threadId", element: <ChatPage /> },
      { path: "c/:conversationId/t/:threadId/history", element: page(<HistoryPage />) },
      { path: "usage", element: page(<UsagePage />) },
      { path: "admin", element: <RequireAdmin>{page(<AdminPage />)}</RequireAdmin> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
