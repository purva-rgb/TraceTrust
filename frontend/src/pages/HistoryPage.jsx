import { useEffect, useState } from "react";
import { api } from "../api.js";
import VerifyResult from "../components/VerifyResult.jsx";
import { History, Search } from "../components/Icons.jsx";

export default function HistoryPage({ token, productUid }) {
  const [labels, setLabels] = useState([]);
  const [query, setQuery] = useState(productUid || "");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api("/labels", { token })
      .then((rows) => {
        if (!cancelled) setLabels(rows || []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function load(uid) {
    const typed = (uid || query).trim();
    if (!typed) return;
    const match = labels.find(
      (row) => row.box_serial === typed || row.serial_number === typed || row.product_uid === typed,
    );
    const next = match?.product_uid || typed;
    setQuery(next);
    setBusy(true);
    setError("");
    try {
      setResult(await api(`/products/${next}/provenance`, { token }));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (productUid) load(productUid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productUid, token]);

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">EVENT HISTORY</span>
          <h1>Event History</h1>
        </div>
      </div>
      <section className="surface">
        <div className="manual-entry">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Box ID"
            aria-label="Box ID"
            list="history-products"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                load(query);
              }
            }}
          />
          <datalist id="history-products">
            {labels.map((row) => (
              <option key={row.product_uid} value={row.box_serial || row.serial_number}>
                {row.box_serial || row.serial_number}
              </option>
            ))}
          </datalist>
          <button className="primary-button" type="button" onClick={() => load(query)} disabled={busy || !query.trim()}>
            <Search />
            {busy ? "Loading…" : "Load"}
          </button>
        </div>
        {error ? <p className="form-error">{error}</p> : null}
      </section>
      {result ? (
        <div style={{ marginTop: 14 }}>
          <VerifyResult result={result} full />
        </div>
      ) : (
        <section className="surface empty-page" style={{ marginTop: 14 }}>
          <History />
          <h2>No event loaded</h2>
        </section>
      )}
    </>
  );
}
