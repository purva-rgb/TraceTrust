import { useState } from "react";
import { api } from "../api.js";

export default function LoginScreen({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("manufacturer@tracetrust.demo");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("MANUFACTURER");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "register") {
        await api("/auth/register", {
          method: "POST",
          body: { email, password, role, organization_name: organizationName },
        });
      }
      const tokenRes = await api("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      const me = await api("/auth/me", { token: tokenRes.access_token });
      onLogin(tokenRes.access_token, me);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card narrow" onSubmit={submit}>
      <h2>{mode === "register" ? "Register" : "Login"}</h2>
      {error ? <p className="error">{error}</p> : null}
      <label>
        Email
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          required
        />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          required
        />
      </label>
      {mode === "register" ? (
        <>
          <label>
            Role
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="MANUFACTURER">Manufacturer</option>
              <option value="DISTRIBUTOR">Distributor</option>
              <option value="RETAILER">Retailer</option>
            </select>
          </label>
          <label>
            Organization name
            <input
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              required
            />
          </label>
        </>
      ) : null}
      <button type="submit" disabled={busy}>
        {busy ? "Please wait…" : mode === "register" ? "Create account" : "Sign in"}
      </button>
      <p className="muted">
        {mode === "register" ? (
          <button type="button" className="secondary" onClick={() => setMode("login")}>
            Already have an account
          </button>
        ) : (
          <button type="button" className="secondary" onClick={() => setMode("register")}>
            First time? Register
          </button>
        )}
      </p>
    </form>
  );
}
