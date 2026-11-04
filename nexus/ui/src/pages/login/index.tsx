import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { setToken } from "../../api/auth";
import { showToast } from "../../shared/toast";
import { Button, Field, Icon, Input } from "@/ui";
import { BareLayout } from "@/shell/BareLayout";
import { shellMessages } from "@/shell/messages";

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
    else if (data) showToast(shellMessages.login.noToken);
  };

  return (
    <BareLayout title={shellMessages.login.title} description={shellMessages.login.description}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field label={shellMessages.login.username} htmlFor="username" tone="onBlue">
          <Input
            id="username"
            tone="onBlue"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </Field>
        <Field label={shellMessages.login.password} htmlFor="password" tone="onBlue">
          <Input
            id="password"
            tone="onBlue"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        <Button type="submit" size="lg" onBlue busy={busy} className="self-start">
          <Icon name="signIn" aria-hidden />
          {shellMessages.login.action}
        </Button>
      </form>
    </BareLayout>
  );
}
