export const GPS_NOT_REQUESTED = { gps_status: "NOT_REQUESTED" };

let sharedCapture = null;

function fromPosition(position) {
  const accuracyM = position.coords.accuracy;
  return {
    gps_status: "CAPTURED",
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    gps_accuracy_cm:
      accuracyM == null || Number.isNaN(accuracyM) ? undefined : Math.max(0, Math.round(accuracyM * 100)),
  };
}

function requestPosition(options) {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => resolve(fromPosition(position)),
      (error) => resolve({ gps_status: error?.code === 1 ? "DENIED" : "UNAVAILABLE" }),
      options,
    );
  });
}

async function captureGpsOnce({ timeout = 20000 } = {}) {
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return { gps_status: "UNAVAILABLE" };
  }
  if (!navigator.geolocation) {
    return { gps_status: "UNAVAILABLE" };
  }
  try {
    const permission = navigator.permissions?.query
      ? await navigator.permissions.query({ name: "geolocation" })
      : null;
    if (permission?.state === "denied") {
      return { gps_status: "DENIED" };
    }
  } catch {
    /* Permissions API is optional; still try geolocation. */
  }
  const cached = await requestPosition({
    enableHighAccuracy: false,
    timeout: Math.min(timeout, 8000),
    maximumAge: 60_000,
  });
  if (cached.gps_status === "CAPTURED" || cached.gps_status === "DENIED") {
    return cached;
  }
  return requestPosition({ enableHighAccuracy: true, timeout, maximumAge: 0 });
}

export function captureGps(options) {
  if (!sharedCapture) {
    sharedCapture = captureGpsOnce(options).finally(() => {
      window.setTimeout(() => {
        sharedCapture = null;
      }, 1500);
    });
  }
  return sharedCapture;
}

function nominatimHeaders() {
  return { Accept: "application/json" };
}

export async function searchPlaces(query) {
  const q = String(query ?? "").trim();
  if (q.length < 2) return [];
  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&limit=6&q=${encodeURIComponent(q)}`;
  const response = await fetch(url, { headers: nominatimHeaders() });
  if (!response.ok) return [];
  const rows = await response.json();
  return (rows || [])
    .map((row) => ({
      label: row.display_name,
      latitude: Number(row.lat),
      longitude: Number(row.lon),
    }))
    .filter((row) => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
}

export async function reversePlace(latitude, longitude) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return "";
  const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${latitude}&lon=${longitude}`;
  const response = await fetch(url, { headers: nominatimHeaders() });
  if (!response.ok) return "";
  const row = await response.json();
  return row?.display_name || row?.name || "";
}

export function parseManualLocation(latText, lngText) {
  const lat = Number(String(latText ?? "").trim());
  const lng = Number(String(lngText ?? "").trim());
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return GPS_NOT_REQUESTED;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return GPS_NOT_REQUESTED;
  return { gps_status: "CAPTURED", latitude: lat, longitude: lng };
}

export function splitLatLng(text) {
  const parts = String(text ?? "").split(",").map((part) => part.trim());
  if (parts.length !== 2) return null;
  const lat = Number(parts[0]);
  const lng = Number(parts[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat: parts[0], lng: parts[1] };
}

export function gpsSummary(gps) {
  if (!gps) return "NOT_REQUESTED";
  if (gps.gps_status === "CAPTURED" && gps.latitude != null && gps.longitude != null) {
    const accuracy = gps.gps_accuracy_cm != null ? ` ±${gps.gps_accuracy_cm} cm` : "";
    return `${gps.latitude.toFixed(5)}, ${gps.longitude.toFixed(5)}${accuracy}`;
  }
  return gps.gps_status || "NOT_REQUESTED";
}

export function e7ToDegrees(value) {
  if (value == null) return null;
  return Number(value) / 10_000_000;
}

export function eventPoints(events) {
  return (events || [])
    .map((event) => {
      const gps = event.gps || {};
      const lat = e7ToDegrees(gps.gps_lat_e7);
      const lng = e7ToDegrees(gps.gps_lng_e7);
      if (gps.gps_status !== "CAPTURED" || lat == null || lng == null) return null;
      return {
        lat,
        lng,
        seq: event.seq,
        event_type: event.event_type,
        gps_status: gps.gps_status,
        gps_source: gps.gps_source || "CLIENT_REPORTED",
      };
    })
    .filter(Boolean);
}
