import { useEffect, useMemo, useState } from "react";
import { api, newIdempotencyKey, pollOperation } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";

export default function SendScreen({ token, me, go }) {
  const recipientType = me.organization_type === "MANUFACTURER" ? "DISTRIBUTOR" : "RETAILER";
  const [inventory, setInventory] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [selected, setSelected] = useState([]);
  const [recipientId, setRecipientId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [inv, parties, ownWarehouses] = await Promise.all([
          api("/inventory", { token }),
          api("/organizations", { token }),
          api("/warehouses", { token }),
        ]);
        if (cancelled) return;
        const recipients = (parties || []).filter((org) => org.organization_type === recipientType);
        setInventory(inv);
        setOrgs(recipients);
        setWarehouses(ownWarehouses);
        if (recipients[0]) setRecipientId(String(recipients[0].organization_id));
        if (ownWarehouses[0]) setSourceId(String(ownWarehouses[0].warehouse_id));
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, recipientType]);

  const destWarehouses = useMemo(() => {
    const org = orgs.find((item) => String(item.organization_id) === String(recipientId));
    return org?.warehouses || [];
  }, [orgs, recipientId]);

  useEffect(() => {
    if (destWarehouses[0]) setDestinationId(String(destWarehouses[0].warehouse_id));
    else setDestinationId("");
  }, [destWarehouses]);

  const keepAtManufacturer = me.organization_type === "MANUFACTURER" && inventory.length > 1;
  const maxSelectable = Math.min(20, inventory.length - (keepAtManufacturer ? 1 : 0));

  function toggle(uid) {
    setSelected((current) => {
      if (current.includes(uid)) return current.filter((item) => item !== uid);
      if (current.length >= maxSelectable) return current;
      return current.concat(uid);
    });
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const created = await api("/transfers", {
        method: "POST",
        token,
        idempotencyKey: newIdempotencyKey(),
        body: {
          recipient_organization_id: Number(recipientId),
          destination_warehouse_id: Number(destinationId),
          source_warehouse_id: sourceId ? Number(sourceId) : null,
          product_uids: selected,
          gps,
        },
      });
      const polled = await pollOperation(token, created.operation_uid);
      setResult({ ...created, ...polled });
      if (polled.status === "CONFIRMED") go(`/transfers/${created.transfer_uid}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Send</h2>
      {error ? <p className="error">{error}</p> : null}
      <label>
        Send to
        <select value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required>
          {!orgs.length ? <option value="">No recipient</option> : null}
          {orgs.map((org) => (
            <option key={org.organization_id} value={org.organization_id}>
              {org.email || org.username || org.organization_name} — {org.organization_type}
            </option>
          ))}
        </select>
      </label>
      <label>
        Destination warehouse
        <select value={destinationId} onChange={(event) => setDestinationId(event.target.value)} required>
          {destWarehouses.map((warehouse) => (
            <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
              {warehouse.warehouse_code} · {warehouse.warehouse_name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Source warehouse
        <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
          {warehouses.map((warehouse) => (
            <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
              {warehouse.warehouse_code} · {warehouse.warehouse_name}
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend>Units ({selected.length}/{maxSelectable})</legend>
        {inventory.map((row) => (
          <label key={row.product_uid} className="check">
            <input
              type="checkbox"
              checked={selected.includes(row.product_uid)}
              onChange={() => toggle(row.product_uid)}
            />
            <span>
              {row.serial_number} <span className="mono">{row.product_uid}</span>
            </span>
          </label>
        ))}
        {!inventory.length ? <p className="muted">Empty.</p> : null}
      </fieldset>
      <GpsField value={gps} onChange={setGps} />
      <button type="submit" disabled={busy || !selected.length}>
        {busy ? "Submitting…" : "Send"}
      </button>
      {result ? (
        <p>
          {result.transfer_uid} · {result.status || result.chain_status}
        </p>
      ) : null}
    </form>
  );
}
