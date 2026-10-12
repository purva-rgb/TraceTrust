import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { copyText } from "../copy.js";

export default function QrCard({ payload, serial, box, seal }) {
  const canvasRef = useRef(null);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    if (!payload || !canvasRef.current) return;
    QRCode.toCanvas(canvasRef.current, payload, { width: 220, margin: 1 }).catch(() => {});
  }, [payload]);

  if (!payload) return null;

  return (
    <div className="qr-card print-label">
      <canvas ref={canvasRef} />
      <dl>
        <dt>Serial</dt>
        <dd>{serial}</dd>
        <dt>Box</dt>
        <dd>{box}</dd>
        <dt>Seal</dt>
        <dd>{seal}</dd>
      </dl>
      <div className="row gap no-print">
        <button type="button" className="secondary-button no-print" onClick={() => copyText(payload).then(() => setCopied("qr"))}>
          {copied === "qr" ? "Copied" : "Copy QR"}
        </button>
        <button type="button" className="secondary-button no-print" onClick={() => window.print()}>
          Print
        </button>
      </div>
    </div>
  );
}
