import { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { QrCode } from "./Icons.jsx";

function cameraMessage(error) {
  const name = error?.name || "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "Camera is blocked. Allow it in the browser, or paste the product ID.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return "No camera was found. Paste the product ID instead.";
  }
  if (name === "NotReadableError") {
    return "The camera is in use by another app. Close it, or paste the product ID.";
  }
  return "The camera could not start. Paste the product ID instead.";
}

async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    const error = new Error("camera unavailable");
    error.name = "NotFoundError";
    throw error;
  }
  const attempts = [{ video: { facingMode: { ideal: "environment" } }, audio: false }, { video: true, audio: false }];
  let last;
  for (const constraints of attempts) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (error) {
      last = error;
      if (error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError") throw error;
    }
  }
  throw last;
}

async function readFrame(video, canvas, context, detector) {
  if (detector) {
    try {
      const codes = await detector.detect(video);
      const text = codes?.[0]?.rawValue?.trim();
      if (text) return text;
    } catch {
      /* The image decoder below still reads this frame. */
    }
  }
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height || !context) return Promise.resolve("");
  const scale = Math.min(1, 720 / width);
  const drawWidth = Math.max(1, Math.floor(width * scale));
  const drawHeight = Math.max(1, Math.floor(height * scale));
  canvas.width = drawWidth;
  canvas.height = drawHeight;
  context.drawImage(video, 0, 0, drawWidth, drawHeight);
  const image = context.getImageData(0, 0, drawWidth, drawHeight);
  const code = jsQR(image.data, drawWidth, drawHeight, { inversionAttempts: "attemptBoth" });
  return code?.data?.trim() || "";
}

export default function QrScanner({ onScan, disabled }) {
  const videoRef = useRef(null);
  const onScanRef = useRef(onScan);
  onScanRef.current = onScan;
  const [active, setActive] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!active) return undefined;
    const video = videoRef.current;
    let stream;
    let timer;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });
    let detector = null;
    try {
      if (typeof window.BarcodeDetector === "function") {
        detector = new window.BarcodeDetector({ formats: ["qr_code"] });
      }
    } catch {
      detector = null;
    }

    function finish(text) {
      if (stopped || !text) return;
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
      setActive(false);
      onScanRef.current(text);
    }

    async function loop() {
      if (stopped || !video || video.readyState < 2) {
        if (!stopped) timer = window.setTimeout(loop, 200);
        return;
      }
      try {
        const text = await readFrame(video, canvas, context, detector);
        if (text) {
          finish(text);
          return;
        }
      } catch {
        /* A single bad frame should not stop the camera. */
      }
      if (!stopped) timer = window.setTimeout(loop, 200);
    }

    (async () => {
      try {
        stream = await openCamera();
        if (stopped) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        video.srcObject = stream;
        await video.play();
        loop();
      } catch (err) {
        if (!stopped) {
          setActive(false);
          setError(cameraMessage(err));
        }
      }
    })();

    return () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
      if (video) video.srcObject = null;
    };
  }, [active]);

  return (
    <div>
      <div className={`scan-frame ${active ? "live" : ""}`}>
        <video ref={videoRef} muted playsInline autoPlay className={active ? "scan-video" : "scan-video hidden"} />
        {active ? null : <QrCode />}
        <span className="scan-corner top-left" />
        <span className="scan-corner top-right" />
        <span className="scan-corner bottom-left" />
        <span className="scan-corner bottom-right" />
      </div>
      <div className="scan-actions">
        {active ? (
          <button className="secondary-button" type="button" onClick={() => setActive(false)}>
            Stop camera
          </button>
        ) : (
          <button className="primary-button" type="button" onClick={() => { setError(""); setActive(true); }} disabled={disabled}>
            <QrCode />
            Scan QR
          </button>
        )}
      </div>
      <p className="field-help">{active ? "Point the camera at the product QR." : "Uses this device's camera. The code is checked as soon as it is read."}</p>
      {error ? <p className="form-error">{error}</p> : null}
    </div>
  );
}
