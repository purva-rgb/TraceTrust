import { useEffect, useState } from "react";
import { api } from "../api.js";
import { AlertTriangle, ArrowRight, Box, Factory, MapPin, PackageCheck, Plus, QrCode, Truck } from "../components/Icons.jsx";

const PATH = ["MANUFACTURER", "DISTRIBUTOR", "RETAILER"];

function cleanName(value) {
  return String(value || "")
    .replace(/\s*\(demo\)/gi, "")
    .replace(/\bdemo\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function PageHeader({ eyebrow, title }) {
  return (
    <div className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
      </div>
    </div>
  );
}

function Metric({ label, value, tone, icon: Icon = PackageCheck }) {
  return (
    <div className="metric">
      <div className={`metric-icon ${tone}`}>
        <Icon />
      </div>
      <div>
        <span className="metric-label">{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

export default function OverviewPage({ token, me, go }) {
  const [inventory, setInventory] = useState([]);
  const [transfers, setTransfers] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api("/inventory", { token }),
      api("/transfers", { token }),
      api("/incidents", { token }).catch(() => []),
    ])
      .then(([units, rows, alerts]) => {
        if (cancelled) return;
        setInventory(units || []);
        setTransfers(rows || []);
        setIncidents(alerts || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const active = transfers.filter((row) => row.transfer_status === "INITIATED" && !row.expired);
  const openAlerts = incidents.filter((row) => row.status === "OPEN" || row.status === "UNDER_REVIEW");
  const frozenAlerts = incidents.filter((row) => row.status === "UNDER_REVIEW");
  const roleIndex = PATH.indexOf(me?.organization_type);
  const orgId = me?.organization_id;
  const heldHere =
    inventory.length > 0 ||
    transfers.some((row) => row.recipient_organization_id === orgId && row.transfer_status === "ACCEPTED");
  const sentOn = transfers.some(
    (row) =>
      row.sender_organization_id === orgId &&
      row.transfer_status === "ACCEPTED" &&
      row.chain_status === "CONFIRMED",
  );
  let reached = 0;
  if (roleIndex >= 0 && heldHere) reached = roleIndex;
  if (roleIndex >= 0 && sentOn) reached = Math.max(reached, Math.min(roleIndex + 1, PATH.length - 1));
  const names = {
    MANUFACTURER: me?.organization_type === "MANUFACTURER" ? cleanName(me.organization_name) : "Manufacturer",
    DISTRIBUTOR: me?.organization_type === "DISTRIBUTOR" ? cleanName(me.organization_name) : "Distributor",
    RETAILER: me?.organization_type === "RETAILER" ? cleanName(me.organization_name) : "Retailer",
  };
  const steps = [
    { icon: Factory, label: "Manufacturer", name: names.MANUFACTURER },
    { icon: Truck, label: "Distributor", name: names.DISTRIBUTOR },
    { icon: MapPin, label: "Retailer", name: names.RETAILER },
  ];
  const freezeAhead = frozenAlerts.length > 0;
  function renderPath() {
    return (
      <>
        <span className="journey-trace" />
        {steps.map((step, index) => {
          const frozen = freezeAhead && index > reached;
          const state = index < reached ? "done" : index === reached ? "current" : "";
          return (
            <div className={`journey-step ${frozen ? "frozen" : ""}`} key={step.label}>
              <div className={`journey-icon ${state}`}>
                <step.icon />
              </div>
              <span>{step.label}</span>
              <strong>{step.name}</strong>
              {frozen ? <em className="frozen-tag">Frozen</em> : null}
            </div>
          );
        })}
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="OPERATIONS OVERVIEW"
        title="Supply Chain Overview"
      />
      {error ? <p className="form-error">{error}</p> : null}
      <div className="overview-intro">
        <div>
          <span className="eyebrow">CONNECTED OPERATIONS</span>
          <h2>Every handoff, accounted for.</h2>
        </div>
        <div className="journey custody-path" style={{ "--reach": reached }}>
          {renderPath()}
        </div>
      </div>
      <div className="metric-grid">
        <Metric label="Units in custody" value={String(inventory.length)} tone="sage" icon={Box} />
        <Metric label="Active shipments" value={String(active.length)} tone="blue" icon={Truck} />
        <Metric label="Open alerts" value={String(openAlerts.length)} tone={openAlerts.length ? "warning" : "sage"} icon={AlertTriangle} />
        <Metric label="Confirmed shipments" value={String(transfers.filter((row) => row.chain_status === "CONFIRMED").length)} tone="sage" />
      </div>
      <div className="overview-grid">
        <section className="surface event-surface">
          <div className="section-heading">
            <h2>Recent transfers</h2>
            <button type="button" onClick={() => go("/supply")}>
              View supply chain
              <ArrowRight />
            </button>
          </div>
          <div className="event-list">
            {transfers.slice(0, 6).map((row) => {
              const incoming = row.recipient_organization_id === me?.organization_id;
              const warning = row.expired || ["REJECTED", "CANCELLED", "FAILED"].includes(row.transfer_status);
              return (
                <div className="event-row" key={row.transfer_uid}>
                  <div className={`event-indicator ${warning ? "warning" : row.transfer_status === "INITIATED" ? "neutral" : ""}`} />
                  <div className="event-copy">
                    <strong>
                      {incoming ? "Incoming" : "Outgoing"} · {row.transfer_status}
                    </strong>
                    <span>
                      {row.item_count} unit{row.item_count === 1 ? "" : "s"} · chain {row.chain_status}
                    </span>
                  </div>
                  <time>{row.expired ? "Expired" : ""}</time>
                </div>
              );
            })}
            {!transfers.length ? <p className="muted">No transfers yet.</p> : null}
          </div>
        </section>
        <section className="surface journey-surface">
          <div className="section-heading">
            <h2>Custody path</h2>
            <button type="button" onClick={() => go("/supply")}>
              View shipments
              <ArrowRight />
            </button>
          </div>
          {freezeAhead ? <p className="error">Upcoming steps are frozen.</p> : null}
          <div className="journey custody-path" style={{ "--reach": reached }}>
          {renderPath()}
        </div>
          <div className="journey-footer">
            <span>Active shipments</span>
            <strong>{active.length}</strong>
          </div>
        </section>
        <section className="surface quick-surface">
          <div className="section-heading">
            <h2>Quick actions</h2>
          </div>
          <div className="quick-actions">
            {me?.organization_type === "MANUFACTURER" ? (
              <button type="button" onClick={() => go("/products")}>
                <Plus />
                <span>
                  <strong>Register product</strong>
                </span>
                <ArrowRight />
              </button>
            ) : null}
            <button type="button" onClick={() => go("/verify")}>
              <QrCode />
                <span>
                  <strong>Verify a product</strong>
                </span>
              <ArrowRight />
            </button>
            {me?.organization_type !== "RETAILER" ? (
              <button type="button" onClick={() => go("/supply")}>
                <Truck />
                <span>
                  <strong>Send a shipment</strong>
                </span>
                <ArrowRight />
              </button>
            ) : null}
          </div>
        </section>
        <section className="surface alerts-surface">
          <div className="section-heading">
            <h2>Needs attention</h2>
            <button type="button" onClick={() => go("/alerts")}>
              View all alerts
              <ArrowRight />
            </button>
          </div>
          {openAlerts.length ? (
            <>
              <div className="attention">
                <AlertTriangle />
                <div>
                  <strong>
                    {openAlerts.length} open investigation{openAlerts.length === 1 ? "" : "s"}
                  </strong>
                </div>
              </div>
              {openAlerts.slice(0, 3).map((row) => (
                <div className="alert-preview" key={row.id}>
                  <span className={`severity ${row.status === "OPEN" ? "high" : "medium"}`}>
                    {row.status === "UNDER_REVIEW" ? "Frozen" : "Open"}
                  </span>
                  <strong className="mono">{row.box_serial || ""}</strong>
                </div>
              ))}
            </>
          ) : (
            <p className="muted">No open alerts for the products on record.</p>
          )}
        </section>
      </div>
    </>
  );
}
