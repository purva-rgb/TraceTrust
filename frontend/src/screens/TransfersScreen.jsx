import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function TransfersScreen({ token, me, go }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api("/transfers", { token })
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="card">
      <h2>Transfers</h2>
      {error ? <p className="error">{error}</p> : null}
      <table className="plain">
        <thead>
          <tr>
            <th>UID</th>
            <th>Direction</th>
            <th>Status</th>
            <th>Chain</th>
            <th>Items</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const incoming = row.recipient_organization_id === me.organization_id;
            return (
              <tr key={row.transfer_uid}>
                <td className="mono">{row.transfer_uid}</td>
                <td>{incoming ? "Incoming" : "Outgoing"}</td>
                <td>
                  {row.transfer_status}
                  {row.expired ? " · expired" : ""}
                </td>
                <td>{row.chain_status}</td>
                <td>{row.item_count}</td>
                <td>
                  <button type="button" className="secondary" onClick={() => go(`/transfers/${row.transfer_uid}`)}>
                    Open
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length ? <p className="muted">No transfers yet.</p> : null}
    </div>
  );
}
