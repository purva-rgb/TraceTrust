import { useEffect, useMemo, useState } from "react";
import { api, newIdempotencyKey, pollOperation } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";
import QrCard from "../components/QrCard.jsx";
import { Plus, Search } from "../components/Icons.jsx";

export default function ProductsPage({ token, me }) {
  const [labels, setLabels] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("All");
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState(null);
  const manufacturer = me?.organization_type === "MANUFACTURER";

  async function refresh() {
    const [labelRows, inventoryRows] = await Promise.all([
      api("/labels", { token }),
      api("/inventory", { token }),
    ]);
    setLabels(labelRows || []);
    setInventory(inventoryRows || []);
  }

  useEffect(() => {
    let cancelled = false;
    refresh()
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const owned = useMemo(() => new Set(inventory.map((row) => row.product_uid)), [inventory]);
  const rows = useMemo(() => {
    return labels
      .map((row) => ({
        ...row,
        status: owned.has(row.product_uid) ? "In custody" : "Sent",
      }))
      .filter((row) => {
        const hay = `${row.product_uid} ${row.serial_number} ${row.box_serial} ${row.seal_id} ${row.custodian || ""}`.toLowerCase();
        const matchesQuery = hay.includes(query.trim().toLowerCase());
        const matchesFilter = filter === "All" || row.status === filter;
        return matchesQuery && matchesFilter;
      });
  }, [labels, owned, query, filter]);

  async function openQr(uid) {
    setError("");
    try {
      setLabel(await api(`/products/${uid}/qr`, { token }));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">PRODUCT REGISTRY</span>
          <h1>Products</h1>
        </div>
        {manufacturer ? (
          <button className="primary-button" type="button" onClick={() => setShowForm((open) => !open)}>
            <Plus />
            Register product
          </button>
        ) : null}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {showForm ? (
        <RegisterForm
          token={token}
          onDone={async (qr) => {
            setLabel(qr);
            setShowForm(false);
            await refresh();
          }}
          onError={setError}
        />
      ) : null}
      <section className="surface table-surface">
        <div className="table-toolbar">
          <div className="search-field">
            <Search />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search product ID, serial, box, seal..."
              aria-label="Search products"
            />
          </div>
          <select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter by status">
            <option>All</option>
            <option>In custody</option>
            <option>Sent</option>
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Box ID</th>
                <th>Serial</th>
                <th>Box</th>
                <th>Seal</th>
                <th>Custodian</th>
                <th>Warehouse</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.product_uid}>
                  <td>
                    <strong className="mono">{row.box_serial}</strong>
                  </td>
                  <td>{row.serial_number}</td>
                  <td className="mono">{row.box_serial}</td>
                  <td className="mono">{row.seal_id}</td>
                  <td>{row.custodian || "—"}</td>
                  <td>{row.warehouse_id ?? "—"}</td>
                  <td>
                    <span className={`status-badge ${row.status === "Sent" ? "in-transit" : ""}`}>
                      <span className="status-dot" />
                      {row.status}
                    </span>
                  </td>
                  <td>
                    <button className="secondary-button" type="button" onClick={() => openQr(row.product_uid)}>
                      QR
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length ? <p className="empty-inline">No products match this view.</p> : null}
        </div>
      </section>
      {label ? (
        <section className="surface" style={{ marginTop: 14 }}>
          <h2>QR label</h2>
          <QrCard
            payload={label.qr_payload}
            serial={label.serial_number}
            box={label.box_serial}
            seal={label.seal_id}
            productUid={label.product_uid}
          />
        </section>
      ) : null}
    </>
  );
}

function RegisterForm({ token, onDone, onError }) {
  const [batches, setBatches] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [serial, setSerial] = useState("");
  const [box, setBox] = useState("");
  const [seal, setSeal] = useState("");
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([api("/batches", { token }), api("/warehouses", { token })])
      .then(([batchRows, warehouseRows]) => {
        if (cancelled) return;
        setBatches(batchRows || []);
        setWarehouses(warehouseRows || []);
        if (batchRows?.[0]) setBatchId(String(batchRows[0].batch_id));
        if (warehouseRows?.[0]) setWarehouseId(String(warehouseRows[0].warehouse_id));
      })
      .catch((err) => onError(err.message));
    return () => {
      cancelled = true;
    };
  }, [token, onError]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setStatus("");
    onError("");
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
      setStatus(`${polled.status}${polled.error_code ? ` · ${polled.error_code}` : ""}`);
      if (polled.status === "CONFIRMED" && created.product_uid) {
        let qr = null;
        try {
          qr = await api(`/products/${created.product_uid}/qr`, { token });
        } catch {
          qr = created.qr_payload
            ? {
                product_uid: created.product_uid,
                qr_payload: created.qr_payload,
                serial_number: serial,
                box_serial: box,
                seal_id: seal,
              }
            : null;
        }
        await onDone(qr);
      }
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="surface" style={{ marginBottom: 14 }} onSubmit={submit}>
      <h2>Register a laptop</h2>
      <div className="grid-2">
        <label className="field">
          Batch
          <select value={batchId} onChange={(event) => setBatchId(event.target.value)} required>
            {batches.map((batch) => (
              <option key={batch.batch_id} value={batch.batch_id}>
                {batch.brand} {batch.model_name} · {batch.batch_number}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Warehouse
          <select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} required>
            {warehouses.map((warehouse) => (
              <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
                {warehouse.warehouse_code} · {warehouse.warehouse_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Laptop serial
          <input value={serial} onChange={(event) => setSerial(event.target.value)} required />
        </label>
        <label className="field">
          Box serial
          <input value={box} onChange={(event) => setBox(event.target.value)} required />
        </label>
        <label className="field">
          Seal ID
          <input value={seal} onChange={(event) => setSeal(event.target.value)} required />
        </label>
      </div>
      <GpsField value={gps} onChange={setGps} />
      <button className="primary-button" type="submit" disabled={busy || !batches.length || !warehouses.length}>
        {busy ? "Registering…" : "Register"}
      </button>
      {status ? <p className="notice">Operation {status}</p> : null}
    </form>
  );
}
