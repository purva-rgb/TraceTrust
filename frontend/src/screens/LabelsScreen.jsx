import { useEffect, useState } from "react";
import { api, newIdempotencyKey, pollOperation } from "../api.js";
import { copyText } from "../copy.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";
import VerifyResult from "../components/VerifyResult.jsx";

async function loadPublicLabels() {
  const response = await fetch("/labels.json", { cache: "no-store" });
  if (!response.ok) return [];
  return response.json();
}

export default function LabelsScreen({ token, me }) {
  const [labels, setLabels] = useState([]);
  const [copied, setCopied] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState("");
  const [batches, setBatches] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [serial, setSerial] = useState("");
  const [box, setBox] = useState("");
  const [seal, setSeal] = useState("");
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [verifyGps, setVerifyGps] = useState(GPS_NOT_REQUESTED);
  const manufacturer = me?.organization_type === "MANUFACTURER";

  async function refresh() {
    if (token) {
      setLabels(await api("/labels", { token }));
      return;
    }
    setLabels(await loadPublicLabels());
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [token]);

  useEffect(() => {
    if (!manufacturer || !token) return undefined;
    let cancelled = false;
    Promise.all([api("/batches", { token }), api("/warehouses", { token })]).then(([batchRows, warehouseRows]) => {
      if (cancelled) return;
      setBatches(batchRows);
      setWarehouses(warehouseRows);
      if (batchRows[0]) setBatchId(String(batchRows[0].batch_id));
      if (warehouseRows[0]) setWarehouseId(String(warehouseRows[0].warehouse_id));
    }).catch((err) => {
      if (!cancelled) setError(err.message);
    });
    return () => {
      cancelled = true;
    };
  }, [manufacturer, token]);

  async function copy(kind, value) {
    await copyText(value);
    setCopied(`${kind}:${value}`);
    setTimeout(() => setCopied(""), 1200);
  }

  async function register(event) {
    event.preventDefault();
    setBusy("register");
    setError("");
    try {
      const created = await api("/products", {
        method: "POST",
        token,
        idempotencyKey: newIdempotencyKey(),
        body: {
          batch_id: Number(batchId),
          warehouse_id: Number(warehouseId),
          serial_number: serial,
          box_serial: box,
          seal_id: seal,
          gps,
        },
      });
      const polled = await pollOperation(token, created.operation_uid);
      if (polled.status !== "CONFIRMED") {
        setError(polled.error_code || polled.status);
      } else {
        setSerial("");
        setBox("");
        setSeal("");
        await refresh();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function verify(event) {
    event.preventDefault();
    setBusy("verify");
    setError("");
    setResult(null);
    const text = query.trim();
    const body = text.startsWith("tt:v1:")
      ? { qr_payload: text, gps: verifyGps }
      : text.includes("-") && text.length > 20
        ? { product_uid: text, gps: verifyGps }
        : { token: text, gps: verifyGps };
    try {
      setResult(await api("/public/verify", { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="stack">
      {manufacturer ? (
        <form className="card" onSubmit={register}>
          <h2>Register</h2>
          {error ? <p className="error">{error}</p> : null}
          <div className="grid-3">
            <label>
              Batch
              <select value={batchId} onChange={(event) => setBatchId(event.target.value)} required>
                {batches.map((batch) => (
                  <option key={batch.batch_id} value={batch.batch_id}>
                    {batch.brand} {batch.model_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Warehouse
              <select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} required>
                {warehouses.map((warehouse) => (
                  <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
                    {warehouse.warehouse_code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Serial
              <input value={serial} onChange={(event) => setSerial(event.target.value)} required />
            </label>
            <label>
              Box
              <input value={box} onChange={(event) => setBox(event.target.value)} required />
            </label>
            <label>
              Seal
              <input value={seal} onChange={(event) => setSeal(event.target.value)} required />
            </label>
          </div>
          <GpsField value={gps} onChange={setGps} />
          <button type="submit" disabled={Boolean(busy)}>
            {busy === "register" ? "Registering…" : "Register"}
          </button>
        </form>
      ) : error ? (
        <p className="error">{error}</p>
      ) : null}

      <div className="card">
        <h2>Labels</h2>
        <table className="plain">
          <thead>
            <tr>
              <th>Custodian</th>
              <th>Serial</th>
              <th>UID</th>
              <th>QR</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {labels.map((row) => (
              <tr key={row.product_uid}>
                <td>{row.custodian || "—"}</td>
                <td>{row.serial_number}</td>
                <td className="mono">{row.product_uid}</td>
                <td className="mono">{row.qr_payload}</td>
                <td className="row gap">
                  <button type="button" className="secondary" onClick={() => copy("uid", row.product_uid)}>
                    {copied === `uid:${row.product_uid}` ? "Copied" : "Copy UID"}
                  </button>
                  <button type="button" className="secondary" onClick={() => copy("qr", row.qr_payload)}>
                    {copied === `qr:${row.qr_payload}` ? "Copied" : "Copy QR"}
                  </button>
                  <button type="button" className="secondary" onClick={() => setQuery(row.qr_payload || row.product_uid)}>
                    Use
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!labels.length ? <p className="muted">No labels yet.</p> : null}
      </div>

      <form className="card" onSubmit={verify}>
        <h2>Verify</h2>
        <label>
          UID or QR
          <input value={query} onChange={(event) => setQuery(event.target.value)} required />
        </label>
        <GpsField value={verifyGps} onChange={setVerifyGps} />
        <button type="submit" disabled={Boolean(busy)}>
          {busy === "verify" ? "Checking…" : "Verify"}
        </button>
      </form>
      <VerifyResult result={result} />
    </div>
  );
}
