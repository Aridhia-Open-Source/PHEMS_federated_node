import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { setToken } from "../../api/auth";
import { showToast } from "../../shared/toast";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const { data } = await api.POST("/login", {
      body: { username, password },
      bodySerializer: () => {
        const f = new FormData();
        f.append("username", username);
        f.append("password", password);
        return f;
      },
    });
    setBusy(false);
    const token = (data as { token?: string } | undefined)?.token;
    if (token) setToken(token);
    else if (data) showToast("Login response had no token");
  };

  return (
    <form className="form login" onSubmit={submit}>
      <h1>Federated Node admin</h1>
      <label><span>Username</span><input value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
      <label><span>Password</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      <button type="submit" disabled={busy}>Log in</button>
    </form>
  );
}
