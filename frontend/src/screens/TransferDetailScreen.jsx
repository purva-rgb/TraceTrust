import { useEffect, useState } from "react";
import { api, pollOperation } from "../api.js";
import { GPS_NOT_REQUESTED } from "../gps.js";
import GpsField from "../components/GpsField.jsx";

function locationCheckMessage(value) {
  if (value === "UNAVAILABLE") {
    return "location_check UNAVAILABLE — GPS was recorded, but the destination warehouse has no coordinates to compare against.";
  }
  if (value === "WITHIN_RADIUS") {
    return "location_check WITHIN_RADIUS — GPS is within 50 km of the destination warehouse (informational).";
  }
  if (value === "OUTSIDE_RADIUS") {
    return "location_check OUTSIDE_RADIUS — GPS is more than 50 km from the destination warehouse (informational, does not block).";
  }
  return value ? `location_check ${value}` : "";
}

export default function TransferDetailScreen({ token, me, transferUid, go }) {
  const [transfer, setTransfer] = useState(null);
  const [items, setItems] = useState([]);
  const [gps, setGps] = useState(GPS_NOT_REQUESTED);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState("");

  async function reload() {
    const data = await api(`/transfers/${transferUid}`, { token });
    setTransfer(data);
    setItems(
      (data.items || []).map((item) => ({
        product_uid: item.product_uid,
        box_serial: item.expected_box_serial || "",
        seal_id: item.expected_seal_id || "",
        condition: "INTACT",
        mode: "SEALED",
        outcome: item.item_outcome,
      })),
    );
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
  }, [token, transferUid]);

  function patchItem(index, field, value) {
    setItems((current) => current.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  }

  const incoming = transfer && transfer.recipient_organization_id === me.organization_id;
  const outgoing = transfer && transfer.sender_organization_id === me.organization_id;
  const canInspect =
    incoming && transfer.transfer_status === "INITIATED" && transfer.chain_status === "CONFIRMED" && !transfer.expired;
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
          items: items.map(({ product_uid, box_serial, seal_id, condition, mode }) => ({
            product_uid,
            box_serial,
            seal_id,
            condition,
            mode,
          })),
        },
      });
      setInfo(locationCheckMessage(result.location_check));
      await reload();
    } catch (err) {
      const detail = err.data?.detail;
      if (detail?.location_check) {
        setInfo(locationCheckMessage(detail.location_check));
      }
      setError(err.message);
      try {
        await reload();
      } catch {
        /* keep the receipts error */
      }
    } finally {
      setBusy("");
    }
  }

  async function runTerminal(kind) {
    setBusy(kind);
    setError("");
    try {
      const body = kind === "accept" ? { gps } : undefined;
      const created = await api(`/transfers/${transferUid}/${kind}`, {
        method: "POST",
        token,
        body,
      });
      const polled = await pollOperation(token, created.operation_uid);
      setInfo(`${kind} ${polled.status}`);
      if (kind === "accept" && polled.status === "CONFIRMED") go("/inventory");
      else await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!transfer) {
    return error ? <p className="error">{error}</p> : <p className="muted">Loading transfer…</p>;
  }

  return (
    <div className="stack">
      <div className="card">
        <h2>Transfer {transfer.transfer_uid}</h2>
        <p>
          {transfer.transfer_status} · chain {transfer.chain_status}
          {transfer.expired ? " · expired" : ""}
        </p>
        {error ? <p className="error">{error}</p> : null}
        {info ? <p className="notice">{info}</p> : null}
        <table className="plain">
          <thead>
            <tr>
              <th>Product</th>
              <th>Expected box</th>
              <th>Expected seal</th>
              <th>Outcome</th>
              <th>laptop_internal_serial_check</th>
            </tr>
          </thead>
          <tbody>
            {(transfer.items || []).map((item) => (
              <tr key={item.product_uid}>
                <td className="mono">{item.product_uid}</td>
                <td>{item.expected_box_serial}</td>
                <td>{item.expected_seal_id}</td>
                <td>{item.item_outcome}</td>
                <td>{item.laptop_internal_serial_check || "NOT_CHECKED"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canInspect ? (
        <div className="card stack">
          <h3>Receipt</h3>
          {items.map((item, index) => (
            <div key={item.product_uid} className="grid-3">
              <label>
                Box for {item.product_uid.slice(0, 8)}…
                <input value={item.box_serial} onChange={(event) => patchItem(index, "box_serial", event.target.value)} />
              </label>
              <label>
                Seal
                <input value={item.seal_id} onChange={(event) => patchItem(index, "seal_id", event.target.value)} />
              </label>
              <label>
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
          <div className="row gap">
            <button type="button" onClick={submitReceipts} disabled={Boolean(busy)}>
              {busy === "receipts" ? "Recording…" : "Record receipts"}
            </button>
            <button type="button" onClick={() => runTerminal("accept")} disabled={Boolean(busy) || !allMatched}>
              {busy === "accept" ? "Accepting…" : "Accept"}
            </button>
            <button type="button" className="danger" onClick={() => runTerminal("reject")} disabled={Boolean(busy)}>
              Reject
            </button>
          </div>
        </div>
      ) : null}

      {outgoing && transfer.transfer_status === "INITIATED" ? (
        <button type="button" className="danger" onClick={() => runTerminal("cancel")} disabled={Boolean(busy)}>
          Cancel transfer
        </button>
      ) : null}
    </div>
  );
}
