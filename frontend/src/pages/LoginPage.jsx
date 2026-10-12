import { useState } from "react";
import { api } from "../api.js";
import { QrCode, ShieldCheck, Truck, Box } from "../components/Icons.jsx";

export default function LoginPage({ onLogin, onVerify }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
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
      setError(err.message || "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <aside className="login-aside">
        <div>
          <div className="brand">
            <div className="brand-mark">
              <ShieldCheck />
            </div>
            <div>
              <strong>TraceTrust</strong>
              <span>Track the Journey. Trust the Trace.</span>
            </div>
          </div>
          <h1>Every handoff, accounted for.</h1>
          <div className="login-points">
            <div>
              <Box />
              <div>
                <strong>Product records</strong>
              </div>
            </div>
            <div>
              <Truck />
              <div>
                <strong>Legal handoffs only</strong>
              </div>
            </div>
            <div>
              <QrCode />
              <div>
                <strong>QR verification</strong>
              </div>
            </div>
          </div>
        </div>
        <div className="environment">
          <span className="live-dot" />
          Staff sign-in · token stays in this browser tab
        </div>
      </aside>
      <main className="login-main">
        <form className="login-card" onSubmit={submit}>
          <span className="eyebrow">{mode === "register" ? "CREATE ACCOUNT" : "STAFF SIGN IN"}</span>
          <h2>{mode === "register" ? "Register your organization" : "Welcome back"}</h2>
          {error ? <p className="form-error">{error}</p> : null}
          <label className="field">
            Email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              minLength={mode === "register" ? 8 : 1}
              required
            />
          </label>
          {mode === "register" ? (
            <>
              <label className="field">
                Role
                <select value={role} onChange={(event) => setRole(event.target.value)}>
                  <option value="MANUFACTURER">Manufacturer</option>
                  <option value="DISTRIBUTOR">Distributor</option>
                  <option value="RETAILER">Retailer</option>
                </select>
              </label>
              <label className="field">
                Organization name
                <input
                  value={organizationName}
                  onChange={(event) => setOrganizationName(event.target.value)}
                  required
                />
              </label>
            </>
          ) : null}
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "Please wait…" : mode === "register" ? "Create account" : "Sign in"}
          </button>
          <p className="form-note">
            {mode === "register" ? (
              <button type="button" className="text-button" onClick={() => setMode("login")}>
                Already have an account
              </button>
            ) : (
              <button type="button" className="text-button" onClick={() => setMode("register")}>
                First time? Register
              </button>
            )}
          </p>
          <p className="form-note">
            <button type="button" className="text-button" onClick={onVerify}>
              Verify a product without signing in
            </button>
          </p>
        </form>
      </main>
    </div>
  );
}
