import { useState } from "react";
import { api } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";
import VerifyResult from "../components/VerifyResult.jsx";
import QrScanner from "../components/QrScanner.jsx";
import { FileSearch, Search } from "../components/Icons.jsx";

export default function VerifyPage() {
  const [query, setQuery] = useState("");
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [searched, setSearched] = useState(false);

  async function verify(raw) {
    const text = (typeof raw === "string" ? raw : query).trim();
    if (!text) return;
    setBusy(true);
    setError("");
    setSearched(true);
    const body = text.startsWith("tt:v1:")
      ? { qr_payload: text, gps }
      : text.includes("-") && text.length > 20
        ? { product_uid: text, gps }
        : { token: text, gps };
    try {
      setResult(await api("/public/verify", { method: "POST", body }));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">RECORD VERIFICATION</span>
          <h1>QR Verification</h1>
        </div>
      </div>
      <div className="verification-grid">
        <section className="surface scan-surface">
          <QrScanner
            disabled={busy}
            onScan={(text) => {
              setQuery(text);
              verify(text);
            }}
          />
          <h2>Check a product record</h2>
          <GpsField value={gps} onChange={setGps} />
          <div className="manual-entry">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Product ID or tt:v1:… QR text"
              aria-label="Product ID"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  verify();
                }
              }}
            />
            <button className="primary-button" type="button" onClick={() => verify()} disabled={busy || !query.trim()}>
              <Search />
              {busy ? "Checking…" : "Verify"}
            </button>
          </div>
          {error ? <p className="form-error">{error}</p> : null}
        </section>
        <section className="surface result-surface">
          {!searched ? (
            <div className="empty-result">
              <FileSearch />
              <h2>Verification result</h2>
            </div>
          ) : busy && !result ? (
            <div className="empty-result">
              <FileSearch />
              <h2>Checking the record</h2>
            </div>
          ) : result ? (
            <VerifyResult result={result} />
          ) : error ? (
            <div className="empty-result">
              <FileSearch />
              <h2>Could not verify</h2>
              <p>{error}</p>
            </div>
          ) : (
            <div className="empty-result">
              <FileSearch />
              <h2>No result</h2>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
