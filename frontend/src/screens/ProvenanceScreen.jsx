import { useEffect, useState } from "react";
import { api } from "../api.js";
import VerifyResult from "../components/VerifyResult.jsx";

export default function ProvenanceScreen({ token, productUid }) {
  const [query, setQuery] = useState(productUid || "");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(uid) {
    if (!uid) return;
    setBusy(true);
    setError("");
    try {
      setResult(await api(`/products/${uid}/provenance`, { token }));
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
    <div className="stack">
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          load(query.trim());
        }}
      >
        <h2>Provenance</h2>
        {error ? <p className="error">{error}</p> : null}
        <label>
          Product UID
          <input value={query} onChange={(event) => setQuery(event.target.value)} required />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Loading…" : "Load"}
        </button>
      </form>
      <VerifyResult result={result} full={Boolean(token)} />
    </div>
  );
}
