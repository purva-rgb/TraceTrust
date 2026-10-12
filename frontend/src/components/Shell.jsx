import { useState } from "react";
import {
  Bell,
  Box,
  ChevronRight,
  CircleHelp,
  History,
  LayoutDashboard,
  Menu,
  QrCode,
  Settings,
  ShieldCheck,
  Truck,
} from "./Icons.jsx";

const NAV = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Products", icon: Box },
  { label: "QR Verification", icon: QrCode },
  { label: "Supply Chain", icon: Truck },
  { label: "Alerts", icon: Bell },
  { label: "Event History", icon: History },
  { label: "Settings", icon: Settings },
];

function initials(me) {
  const source = String(me?.organization_name || me?.username || "TT").replace(/\s*\(demo\)/gi, "").replace(/\bdemo\b/gi, "").trim() || "TT";
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function roleLabel(type) {
  if (!type) return "";
  return type.charAt(0) + type.slice(1).toLowerCase();
}

export default function Shell({ me, active, alertCount = 0, onNavigate, onLogout, publicMode = false, children }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const items = publicMode ? NAV.filter((item) => item.label === "QR Verification") : NAV;

  function navigate(label) {
    setMobileOpen(false);
    onNavigate(label);
  }

  return (
    <div className="app-shell">
      <div className={`mobile-overlay ${mobileOpen ? "show" : ""}`} onClick={() => setMobileOpen(false)} />
      <div className={`sidebar-wrap ${mobileOpen ? "open" : ""}`}>
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">
              <ShieldCheck />
            </div>
            <div>
              <strong>TraceTrust</strong>
              <span>Track the Journey. Trust the Trace.</span>
            </div>
          </div>
          <div className="workspace-label">OPERATIONS</div>
          <nav aria-label="Primary navigation">
            {items.map(({ label, icon: Icon }) => (
              <button
                key={label}
                type="button"
                className={`nav-item ${active === label ? "active" : ""}`}
                onClick={() => navigate(label)}
              >
                <Icon />
                <span>{label}</span>
                {label === "Alerts" && alertCount > 0 ? <span className="nav-count">{alertCount}</span> : null}
              </button>
            ))}
          </nav>
          <div className="sidebar-footer">
            <div className="environment">
              <span className="live-dot" />
              {publicMode ? "Public verification" : "Live records"}
            </div>
            {me ? (
              <button type="button" className="user-block" onClick={() => navigate("Settings")}>
                <div className="avatar">{initials(me)}</div>
                <div>
                  <strong>{String(me.organization_name || me.username || "").replace(/\s*\(demo\)/gi, "").replace(/\bdemo\b/gi, "").trim()}</strong>
                  <span>{roleLabel(me.organization_type)}</span>
                </div>
                <ChevronRight />
              </button>
            ) : (
              <button type="button" className="user-block" onClick={onLogout}>
                <div className="avatar">IN</div>
                <div>
                  <strong>Sign in</strong>
                  <span>Staff workspace</span>
                </div>
                <ChevronRight />
              </button>
            )}
          </div>
        </aside>
      </div>
      <div className="main-shell">
        <header className="topbar">
          <button type="button" className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu />
          </button>
          <div className="breadcrumbs">
            <span>Workspace</span>
            <ChevronRight />
            <strong>{active}</strong>
          </div>
          <div className="top-actions">
            <span className="simulated-label">
              <span className="live-dot" />
              {publicMode ? "No sign-in required" : "Live records"}
            </span>
            <button type="button" className="icon-button" aria-label="About this workspace" title="Checks describe records. A high score means more reason to review.">
              <CircleHelp />
            </button>
            {me ? <div className="top-avatar">{initials(me)}</div> : null}
          </div>
        </header>
        <main className="workspace">{children}</main>
      </div>
    </div>
  );
}
