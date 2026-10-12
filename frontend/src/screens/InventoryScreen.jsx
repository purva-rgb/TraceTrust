import { useEffect, useState } from "react";
import { api } from "../api.js";
import QrCard from "../components/QrCard.jsx";

export default function InventoryScreen({ token, go }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [label, setLabel] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api("/inventory", { token })
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

  async function loadQr(uid) {
    setError("");
    try {
      setLabel(await api(`/products/${uid}/qr`, { token }));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h2>Inventory</h2>
        {error ? <p className="error">{error}</p> : null}
        <table className="plain">
          <thead>
            <tr>
              <th>UID</th>
              <th>Serial</th>
              <th>Warehouse</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.product_uid}>
                <td className="mono">{row.product_uid}</td>
                <td>{row.serial_number}</td>
                <td>{row.warehouse_id ?? "—"}</td>
                <td className="row gap">
                  <button type="button" className="secondary" onClick={() => go(`/products/${row.product_uid}`)}>
                    Provenance
                  </button>
                  <button type="button" className="secondary" onClick={() => loadQr(row.product_uid)}>
                    QR
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length ? <p className="muted">Empty.</p> : null}
      </div>
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
