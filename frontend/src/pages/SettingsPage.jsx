function roleLabel(type) {
  if (!type) return "—";
  return type.charAt(0) + type.slice(1).toLowerCase();
}

export default function SettingsPage({ me, onLogout }) {
  const rows = [
    ["Organization", String(me?.organization_name || "").replace(/\s*\(demo\)/gi, "").replace(/\bdemo\b/gi, "").trim()],
    ["Role", roleLabel(me?.organization_type)],
    ["Email", /demo/i.test(me?.email || "") ? "" : me?.email || me?.username],
    ["Account status", me?.status],
    ["Organization status", me?.organization_status],
  ];

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">ACCOUNT</span>
          <h1>Settings</h1>
        </div>
        <button className="secondary-button" type="button" onClick={onLogout}>
          Sign out
        </button>
      </div>
      <section className="surface detail-surface">
        <div className="section-heading">
          <h2>Signed-in organization</h2>
        </div>
        <div className="detail-rows">
          {rows.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value || "—"}</strong>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
