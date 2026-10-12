import { useEffect, useState } from "react";
import { api } from "../api.js";

function statusLabel(status) {
  if (status === "UNDER_REVIEW") return "Frozen";
  if (status === "DISMISSED") return "Ignored";
  return "Open";
}

export default function AlertsPage({ token }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  function load() {
    return api("/incidents", { token }).then((data) => setRows(data || []));
  }

  useEffect(() => {
    let cancelled = false;
    api("/incidents", { token })
      .then((data) => {
        if (!cancelled) setRows(data || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const seen = new Set();
  const alerts = [];
  for (const row of rows) {
    if (row.status !== "OPEN" && row.status !== "UNDER_REVIEW") continue;
    const boxKey = row.box_serial || row.product_uid;
    if (seen.has(boxKey)) continue;
    seen.add(boxKey);
    const items = row.alerts?.length ? row.alerts : [{ id: row.id, rule_code: row.status, reason: "" }];
    const latest = items[items.length - 1];
    alerts.push({
      key: boxKey,
      id: row.id,
      status: row.status,
      box_serial: row.box_serial,
      rule_code: latest.rule_code,
      reason: latest.reason,
      opened: row.created_at,
    });
  }
  const selected = alerts.find((alert) => alert.key === selectedKey) || null;

  async function decide(decision) {
    if (!selected) return;
    setBusy(decision);
    setError("");
    setNote("");
    try {
      await api(`/incidents/${selected.id}/decision`, { method: "POST", token, body: { decision } });
      await load();
      if (decision === "ignore") {
        setSelectedKey("");
        setNote(`Box ${selected.box_serial || "record"} was ignored. Upcoming steps can continue.`);
      } else {
        setNote(`Box ${selected.box_serial || "record"} is frozen. Upcoming steps cannot continue.`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">INVESTIGATION QUEUE</span>
          <h1>Alerts</h1>
        </div>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {note ? <p className="notice">{note}</p> : null}
      <section className="surface table-surface">
        <div className="table-toolbar">
          <h2 className="table-title">
            Alerts <span>{alerts.length} total</span>
          </h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Box ID</th>
                <th>Alert</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <tr
                  key={alert.key}
                  className={`alert-row ${selectedKey === alert.key ? "selected" : ""}`}
                  onClick={() => {
                    setSelectedKey(alert.key);
                    setNote("");
                  }}
                >
                  <td>
                    <span className={`severity ${alert.status === "OPEN" ? "high" : "medium"}`}>{statusLabel(alert.status)}</span>
                  </td>
                  <td>
                    <strong className="mono">{alert.box_serial || "—"}</strong>
                  </td>
                  <td>
                    <strong>{alert.rule_code}</strong>
                  </td>
                  <td>{alert.opened || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!alerts.length ? <p className="empty-inline">No alerts.</p> : null}
        </div>
      </section>
      {selected ? (
        <section className="surface decision-panel">
          <h2>Box {selected.box_serial || "record"}</h2>
          <p>{selected.reason || selected.rule_code}</p>
          <div className="row gap">
            <button className="secondary-button" type="button" onClick={() => decide("ignore")} disabled={Boolean(busy)}>
              {busy === "ignore" ? "Ignoring…" : "Ignore"}
            </button>
            <button className="primary-button" type="button" onClick={() => decide("freeze")} disabled={Boolean(busy) || selected.status === "UNDER_REVIEW"}>
              {selected.status === "UNDER_REVIEW" ? "Steps are frozen" : busy === "freeze" ? "Freezing…" : "Freeze upcoming steps"}
            </button>
          </div>
        </section>
      ) : null}
    </>
  );
}
