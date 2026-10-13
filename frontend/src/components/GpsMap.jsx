import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export default function GpsMap({ points, showTable = true }) {
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const [tilesFailed, setTilesFailed] = useState(false);

  useEffect(() => {
    if (!points?.length || tilesFailed) return undefined;
    const map = L.map(mapRef.current, { scrollWheelZoom: false });
    const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 18,
    });
    tiles.on("tileerror", () => setTilesFailed(true));
    tiles.addTo(map);
    const group = L.featureGroup(
      points.map((point) =>
        L.circleMarker([point.lat, point.lng], {
          radius: 8,
          color: "#3d8bfd",
          fillColor: "#3d8bfd",
          fillOpacity: 0.85,
        }).bindPopup(
          `seq ${point.seq} · ${point.event_type}<br/>client-reported ${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`,
        ),
      ),
    ).addTo(map);
    map.fitBounds(group.getBounds().pad(0.35));
    layerRef.current = map;
    return () => {
      map.remove();
      layerRef.current = null;
    };
  }, [points, tilesFailed]);

  if (!points?.length) {
    return <p className="muted">No GPS.</p>;
  }

  return (
    <div>
      {!tilesFailed ? <div ref={mapRef} className="map" /> : null}
      {tilesFailed ? <p className="muted">Map unavailable.</p> : null}
      {showTable ? <table className="plain gps-table">
        <thead>
          <tr>
            <th>Seq</th>
            <th>Event</th>
            <th>Latitude</th>
            <th>Longitude</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={`${point.seq}-${point.event_type}`}>
              <td>{point.seq}</td>
              <td>{point.event_type}</td>
              <td>{point.lat.toFixed(6)}</td>
              <td>{point.lng.toFixed(6)}</td>
              <td>{point.gps_source || "CLIENT_REPORTED"}</td>
            </tr>
          ))}
        </tbody>
      </table> : null}
    </div>
  );
}
