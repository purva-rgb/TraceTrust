import { useEffect, useMemo, useState } from "react";
import { api, newIdempotencyKey, pollOperation } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";
import { ArrowRight, Truck } from "../components/Icons.jsx";

function locationCheckMessage(value) {
  if (value === "UNAVAILABLE") return "GPS was recorded, but the destination warehouse has no coordinates to compare.";
  if (value === "WITHIN_RADIUS") return "GPS is within 50 km of the destination warehouse. This is informational.";
  if (value === "OUTSIDE_RADIUS") return "GPS is more than 50 km from the destination warehouse. This does not block the handoff.";
  return value ? `Location check: ${value}` : "";
}

export default function SupplyPage({ token, me, transferUid, go }) {
  if (transferUid) {
    return <TransferDetail token={token} me={me} transferUid={transferUid} go={go} />;
  }
  return <TransferHome token={token} me={me} go={go} />;
}

function TransferHome({ token, me, go }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [showSend, setShowSend] = useState(false);
  const canSend = me?.organization_type === "MANUFACTURER" || me?.organization_type === "DISTRIBUTOR";

  function reload() {
    return api("/transfers", { token }).then(setRows);
  }

  useEffect(() => {
    let cancelled = false;
    reload()
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const active = rows.find((row) => row.transfer_status === "INITIATED" && !row.expired);

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">MOVEMENT TRACKING</span>
          <h1>Supply Chain</h1>
        </div>
        {canSend ? (
          <button className="primary-button" type="button" onClick={() => setShowSend((open) => !open)}>
            <Truck />
            New shipment
          </button>
        ) : null}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {showSend ? <SendForm token={token} me={me} go={go} /> : null}
      {active ? (
        <section className="surface shipment-summary">
          <div>
            <span className="eyebrow">ACTIVE SHIPMENT</span>
            <h2>{active.transfer_status}</h2>
            <p>
              {active.item_count} unit{active.item_count === 1 ? "" : "s"} · {active.transfer_status} · chain {active.chain_status}
            </p>
          </div>
          <button className="secondary-button" type="button" onClick={() => go(`/supply/${active.transfer_uid}`)}>
            Open
            <ArrowRight />
          </button>
        </section>
      ) : null}
      <section className="surface table-surface">
        <div className="table-toolbar">
          <h2 className="table-title">
            Shipments <span>{rows.length} total</span>
          </h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Transfer</th>
                <th>Direction</th>
                <th>Status</th>
                <th>Chain</th>
                <th>Units</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const incoming = row.recipient_organization_id === me?.organization_id;
                return (
                  <tr key={row.transfer_uid}>
                    <td>
                      <strong className="mono">{row.transfer_uid}</strong>
                    </td>
                    <td>{incoming ? "Incoming" : "Outgoing"}</td>
                    <td>
                      <span className={`status-badge ${row.transfer_status === "INITIATED" ? "in-transit" : row.expired ? "review" : ""}`}>
                        <span className="status-dot" />
                        {row.transfer_status}
                        {row.expired ? " · expired" : ""}
                      </span>
                    </td>
                    <td>{row.chain_status}</td>
                    <td>{row.item_count}</td>
                    <td>
                      <button className="secondary-button" type="button" onClick={() => go(`/supply/${row.transfer_uid}`)}>
                        Open
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!rows.length ? <p className="empty-inline">No transfers yet.</p> : null}
        </div>
      </section>
    </>
  );
}

function SendForm({ token, me, go }) {
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
  const [frozenUids, setFrozenUids] = useState([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api("/inventory", { token }), api("/organizations", { token }), api("/warehouses", { token })])
      .then(([inv, parties, ownWarehouses]) => {
        if (cancelled) return;
        const recipients = (parties || []).filter((org) => org.organization_type === recipientType);
        setInventory(inv || []);
        setOrgs(recipients);
        setWarehouses(ownWarehouses || []);
        if (recipients[0]) setRecipientId(String(recipients[0].organization_id));
        if (ownWarehouses?.[0]) setSourceId(String(ownWarehouses[0].warehouse_id));
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token, recipientType]);

  useEffect(() => {
    let cancelled = false;
    api("/incidents", { token })
      .then((rows) => {
        if (cancelled) return;
        setFrozenUids(
          (rows || [])
            .filter((row) => row.status === "UNDER_REVIEW")
            .map((row) => row.product_uid),
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [token]);

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
    if (frozenUids.includes(uid)) return;
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
      if (polled.status === "CONFIRMED") go(`/supply/${created.transfer_uid}`);
      else setError(polled.error_detail || polled.error_code || polled.status);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="surface" style={{ marginBottom: 14 }} onSubmit={submit}>
      <h2>Send units</h2>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="grid-2">
        <label className="field">
          Send to
          <select value={recipientId} onChange={(event) => setRecipientId(event.target.value)} required>
            {!orgs.length ? <option value="">No recipient</option> : null}
            {orgs.map((org) => (
              <option key={org.organization_id} value={org.organization_id}>
                {org.organization_name} — {org.organization_type}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Destination warehouse
          <select value={destinationId} onChange={(event) => setDestinationId(event.target.value)} required>
            {destWarehouses.map((warehouse) => (
              <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
                {warehouse.warehouse_code} · {warehouse.warehouse_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Source warehouse
          <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
            {warehouses.map((warehouse) => (
              <option key={warehouse.warehouse_id} value={warehouse.warehouse_id}>
                {warehouse.warehouse_code} · {warehouse.warehouse_name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, marginBottom: 12 }}>
        <legend>
          Units ({selected.length}/{maxSelectable || 0})
        </legend>
        {inventory.map((row) => (
          <label key={row.product_uid} className="field check">
            <input
              type="checkbox"
              checked={selected.includes(row.product_uid)}
              disabled={frozenUids.includes(row.product_uid)}
              onChange={() => toggle(row.product_uid)}
            />
            <span>
              {row.serial_number}
              {frozenUids.includes(row.product_uid) ? " · Frozen" : ""}
            </span>
          </label>
        ))}
        {!inventory.length ? <p className="muted">No units in custody.</p> : null}
        {keepAtManufacturer ? <p className="muted">Leave at least one unit with the manufacturer.</p> : null}
      </fieldset>
      <GpsField value={gps} onChange={setGps} />
      {frozenUids.length ? <p className="form-error">Upcoming steps for a selected box are frozen.</p> : null}
      <button className="primary-button" type="submit" disabled={busy || !selected.length}>
        {busy ? "Submitting…" : "Send"}
      </button>
    </form>
  );
}

function TransferDetail({ token, me, transferUid, go }) {
  const [transfer, setTransfer] = useState(null);
  const [items, setItems] = useState([]);
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState("");
  const [frozen, setFrozen] = useState(false);

  async function reload() {
    const data = await api(`/transfers/${transferUid}`, { token });
    setTransfer(data);
    setItems(
      (data.items || []).map((item) => ({
        product_uid: item.product_uid,
        box_serial: item.expected_box_serial || "",
        seal_id: item.expected_seal_id || "",
        condition: "INTACT",
        outcome: item.item_outcome,
        laptop_internal_serial_check: item.laptop_internal_serial_check,
        expected_box_serial: item.expected_box_serial,
        expected_seal_id: item.expected_seal_id,
      })),
    );
  }

  useEffect(() => {
    let cancelled = false;
    reload().catch((err) => {
      if (!cancelled) setError(err.message);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, transferUid]);

  function patchItem(index, field, value) {
    setItems((current) => current.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  }

  useEffect(() => {
    if (!transfer?.items) return undefined;
    let cancelled = false;
    api("/incidents", { token })
      .then((rows) => {
        if (cancelled) return;
        const open = new Set(
          (rows || [])
            .filter((row) => row.status === "UNDER_REVIEW")
            .map((row) => row.product_uid),
        );
        setFrozen(transfer.items.some((item) => open.has(item.product_uid)));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [token, transfer]);

  const incoming = transfer && transfer.recipient_organization_id === me.organization_id;
  const outgoing = transfer && transfer.sender_organization_id === me.organization_id;
  const canInspect = incoming && transfer.transfer_status === "INITIATED" && transfer.chain_status === "CONFIRMED" && !transfer.expired;
  const allMatched = items.length && items.every((item) => item.outcome === "MATCHED");

  async function submitReceipts() {
    setBusy("receipts");
    setError("");
    setInfo("");
    try {
      const result = await api(`/transfers/${transferUid}/receipts`, {
        method: "POST",
        token,
        body: {
          gps,
          items: items.map(({ product_uid, box_serial, seal_id, condition }) => ({
            product_uid,
            box_serial,
            seal_id,
            condition,
            mode: "SEALED",
          })),
        },
      });
      setInfo(locationCheckMessage(result.location_check));
      await reload();
    } catch (err) {
      if (err.data?.detail?.location_check) setInfo(locationCheckMessage(err.data.detail.location_check));
      setError(err.message);
      try {
        await reload();
      } catch {
        /* keep the receipt error */
      }
    } finally {
      setBusy("");
    }
  }

  async function runTerminal(kind) {
    setBusy(kind);
    setError("");
    try {
      const created = await api(`/transfers/${transferUid}/${kind}`, {
        method: "POST",
        token,
        body: kind === "accept" ? { gps } : undefined,
      });
      const polled = await pollOperation(token, created.operation_uid);
      setInfo(`${kind} ${polled.status}`);
      if (kind === "accept" && polled.status === "CONFIRMED") go("/products");
      else await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!transfer) {
    return error ? <p className="form-error">{error}</p> : <p className="muted">Loading transfer…</p>;
  }

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">SHIPMENT</span>
          <h1>{transfer.transfer_status}</h1>
          <p>
            {transfer.transfer_status} · chain {transfer.chain_status}
            {transfer.expired ? " · expired" : ""}
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => go("/supply")}>
          All shipments
        </button>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {info ? <p className="notice">{info}</p> : null}
      <section className="surface table-surface">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Expected box</th>
                <th>Expected seal</th>
                <th>Outcome</th>
                <th>Laptop serial check</th>
              </tr>
            </thead>
            <tbody>
              {(transfer.items || []).map((item) => (
                <tr key={item.product_uid}>
                  <td className="mono">{item.expected_box_serial}</td>
                  <td>{item.expected_seal_id}</td>
                  <td>{item.item_outcome}</td>
                  <td>{item.laptop_internal_serial_check || "NOT_CHECKED"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {canInspect ? (
        <section className="surface stack" style={{ marginTop: 14 }}>
          <h2>Sealed receipt</h2>
          {items.map((item, index) => (
            <div className="grid-3" key={item.product_uid}>
              <label className="field">
                Box · {item.expected_box_serial || item.box_serial}
                <input value={item.box_serial} onChange={(event) => patchItem(index, "box_serial", event.target.value)} />
              </label>
              <label className="field">
                Seal
                <input value={item.seal_id} onChange={(event) => patchItem(index, "seal_id", event.target.value)} />
              </label>
              <label className="field">
                Condition
                <select value={item.condition} onChange={(event) => patchItem(index, "condition", event.target.value)}>
                  <option>INTACT</option>
                  <option>BROKEN</option>
                  <option>MISSING</option>
                  <option>UNKNOWN</option>
                </select>
              </label>
            </div>
          ))}
          <GpsField value={gps} onChange={setGps} />
          {frozen ? <p className="form-error">Upcoming steps for these units are frozen.</p> : null}
          <div className="row gap">
            <button className="primary-button" type="button" onClick={submitReceipts} disabled={Boolean(busy) || frozen}>
              {busy === "receipts" ? "Recording…" : "Record receipts"}
            </button>
            <button className="secondary-button" type="button" onClick={() => runTerminal("accept")} disabled={Boolean(busy) || !allMatched || frozen}>
              {busy === "accept" ? "Accepting…" : "Accept"}
            </button>
            <button className="secondary-button" type="button" onClick={() => runTerminal("reject")} disabled={Boolean(busy)}>
              Reject
            </button>
          </div>
        </section>
      ) : null}
      {outgoing && transfer.transfer_status === "INITIATED" ? (
        <p style={{ marginTop: 14 }}>
          <button className="secondary-button" type="button" onClick={() => runTerminal("cancel")} disabled={Boolean(busy)}>
            Cancel transfer
          </button>
        </p>
      ) : null}
    </>
  );
}
