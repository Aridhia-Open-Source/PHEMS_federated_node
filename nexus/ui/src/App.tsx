import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import { useToken } from "./api/auth";
import { ToastProvider } from "./ui";
import { ToastBridge } from "./shared/toast";
import { AppLayout } from "./shell/AppLayout";
import Login from "./pages/login";
import { pages } from "./routes";

export default function App() {
  const token = useToken();
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ToastBridge />
        {token ? <Shell /> : <Login />}
      </ToastProvider>
    </QueryClientProvider>
  );
}

function Shell() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="projects" replace />} />
          {pages.map((p) => <Route key={p.path} path={`${p.path}/*`} element={<p.element />} />)}
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
