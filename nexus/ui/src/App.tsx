import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import { setToken, useToken } from "./api/auth";
import { Toasts } from "./shared/toast";
import Login from "./pages/login";
import { pages } from "./routes";

export default function App() {
  const token = useToken();
  return (
    <QueryClientProvider client={queryClient}>
      <Toasts />
      {token ? <Shell /> : <Login />}
    </QueryClientProvider>
  );
}

function Shell() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <div className="layout">
        <nav className="sidebar">
          <strong>FN admin</strong>
          {pages.map((p) => <NavLink key={p.path} to={p.path}>{p.label}</NavLink>)}
          <button onClick={() => { setToken(null); queryClient.clear(); }}>Log out</button>
        </nav>
        <main>
          <Routes>
            <Route index element={<Navigate to="projects" replace />} />
            {pages.map((p) => <Route key={p.path} path={`${p.path}/*`} element={<p.element />} />)}
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
