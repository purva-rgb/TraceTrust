import { useEffect, useState } from "react";
import { api, newIdempotencyKey, pollOperation } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";
import QrCard from "../components/QrCard.jsx";

export default function RegisterScreen({ token }) {
  const [batches, setBatches] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [serial, setSerial] = useState("");
  const [box, setBox] = useState("");
  const [seal, setSeal] = useState("");
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState(null);
  const [label, setLabel] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [batchRows, warehouseRows] = await Promise.all([
          api("/batches", { token }),
          api("/warehouses", { token }),
        ]);
        if (cancelled) return;
        setBatches(batchRows);
        setWarehouses(warehouseRows);
        if (batchRows[0]) setBatchId(String(batchRows[0].batch_id));
        if (warehouseRows[0]) setWarehouseId(String(warehouseRows[0].warehouse_id));
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setLabel(null);
    setOperation(null);
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
      setOperation(polled);
      if (polled.status === "CONFIRMED" && created.product_uid) {
        try {
          const qr = await api(`/products/${created.product_uid}/qr`, { token });
          setLabel(qr);
        } catch {
          if (created.qr_payload) {
            setLabel({
              product_uid: created.product_uid,
              qr_payload: created.qr_payload,
              serial_number: serial,
              box_serial: box,
              seal_id: seal,
            });
          }
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <form className="card" onSubmit={submit}>
        <h2>Register</h2>
        {error ? <p className="error">{error}</p> : null}
        <label>
          Batch
          <select value={batchId} onChange={(event) => setBatchId(event.target.value)} required>
            {batches.map((batch) => (
              <option key={batch.batch_id} value={batch.batch_id}>
                {batch.brand} {batch.model_name} · {batch.batch_number}
              </option>
            ))}
          </select>
        </label>
        <label>
          Warehouse
          <select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} required>
            {warehouses.map((warehouse) => (
              <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
                {warehouse.warehouse_code} · {warehouse.warehouse_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Laptop serial
          <input value={serial} onChange={(event) => setSerial(event.target.value)} required />
        </label>
        <label>
          Box serial
          <input value={box} onChange={(event) => setBox(event.target.value)} required />
        </label>
        <label>
          Seal ID
          <input value={seal} onChange={(event) => setSeal(event.target.value)} required />
        </label>
        <GpsField value={gps} onChange={setGps} />
        <button type="submit" disabled={busy}>
          {busy ? "Registering…" : "Register"}
        </button>
      </form>
      {operation ? (
        <p>
          Operation {operation.operation_uid}: <strong>{operation.status}</strong>
          {operation.error_code ? ` · ${operation.error_code}` : ""}
        </p>
      ) : null}
      <QrCard
        payload={label?.qr_payload}
        serial={label?.serial_number}
        box={label?.box_serial}
        seal={label?.seal_id}
        productUid={label?.product_uid}
      />
    </div>
  );
}
