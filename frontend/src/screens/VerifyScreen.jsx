import { useState } from "react";
import { api } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";
import VerifyResult from "../components/VerifyResult.jsx";

export default function VerifyScreen() {
  const [query, setQuery] = useState("");
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    const text = query.trim();
    const body = text.startsWith("tt:v1:")
      ? { qr_payload: text, gps }
      : text.includes("-") && text.length > 20
        ? { product_uid: text, gps }
        : { token: text, gps };
    try {
      setResult(await api("/public/verify", { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <form className="card" onSubmit={submit}>
        <h2>Verify</h2>
        {error ? <p className="error">{error}</p> : null}
        <label>
          UID or QR
          <input value={query} onChange={(event) => setQuery(event.target.value)} required />
        </label>
        <GpsField value={gps} onChange={setGps} />
        <button type="submit" disabled={busy}>
          {busy ? "Checking…" : "Verify"}
        </button>
      </form>
      <VerifyResult result={result} />
    </div>
  );
}
