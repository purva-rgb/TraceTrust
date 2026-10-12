import { useEffect, useState } from "react";
import { captureGps, gpsSummary, reversePlace, searchPlaces } from "../gps.js";

export default function GpsField({ value, onChange, auto = true }) {
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState("");
  const [placeLabel, setPlaceLabel] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const denied = value?.gps_status === "DENIED" || value?.gps_status === "UNAVAILABLE";

  useEffect(() => {
    if (!auto || value?.gps_status === "CAPTURED") return undefined;
    let cancelled = false;
    (async () => {
      setBusy(true);
      setHint("Detecting location… allow it if the browser asks.");
      const next = await captureGps();
      if (cancelled) return;
      onChange(next);
      if (next.gps_status === "CAPTURED") {
        setHint("");
        reversePlace(next.latitude, next.longitude)
          .then((label) => {
            if (!cancelled && label) setPlaceLabel(label);
          })
          .catch(() => {});
      } else if (next.gps_status === "DENIED") {
        setHint("Location is blocked. Search a place instead.");
      } else {
        setHint("GPS could not be detected. Search a place instead.");
      }
      setBusy(false);
    })();
    return () => {
      cancelled = true;
    };
    // Auto-detect once when the field mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto]);

  useEffect(() => {
    if (!denied) return undefined;
    const text = query.trim();
    if (text.length < 2) {
      setResults([]);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        setResults(await searchPlaces(text));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 400);
    return () => window.clearTimeout(timer);
  }, [denied, query]);

  function pickPlace(place) {
    setQuery(place.label);
    setPlaceLabel(place.label);
    setResults([]);
    setHint("");
    onChange({
      gps_status: "CAPTURED",
      latitude: place.latitude,
      longitude: place.longitude,
    });
  }

  async function retryGps() {
    setBusy(true);
    setHint("Detecting location…");
    const next = await captureGps();
    onChange(next);
    if (next.gps_status === "CAPTURED") {
      setHint("");
      setPlaceLabel((await reversePlace(next.latitude, next.longitude).catch(() => "")) || "");
    } else if (next.gps_status === "DENIED") {
      setHint("Location is blocked. Search a place instead.");
    } else {
      setHint("GPS could not be detected. Search a place instead.");
    }
    setBusy(false);
  }

  return (
    <div className="gps-field">
      <div className="row gap">
        <span className={`gps-status status-${(value?.gps_status || "NOT_REQUESTED").toLowerCase()}`}>
          {busy ? "Detecting location…" : placeLabel || gpsSummary(value)}
        </span>
        {denied && !busy ? (
          <button type="button" className="secondary" onClick={retryGps}>
            Use my location
          </button>
        ) : null}
      </div>
      {hint ? <p className="muted">{hint}</p> : null}
      {denied && !busy ? (
        <div className="place-search">
          <label>
            Search location
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search like Google Maps — city, area, landmark"
              autoComplete="off"
            />
          </label>
          {searching ? <p className="muted">Searching…</p> : null}
          {results.length ? (
            <ul className="place-suggest">
              {results.map((place) => (
                <li key={`${place.latitude}-${place.longitude}-${place.label}`}>
                  <button type="button" onClick={() => pickPlace(place)}>
                    {place.label}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
