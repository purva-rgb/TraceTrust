import { useEffect, useMemo, useState } from "react";
import InventoryScreen from "./screens/InventoryScreen.jsx";
import LabelsScreen from "./screens/LabelsScreen.jsx";
import LoginScreen from "./screens/LoginScreen.jsx";
import ProvenanceScreen from "./screens/ProvenanceScreen.jsx";
import RegisterScreen from "./screens/RegisterScreen.jsx";
import SendScreen from "./screens/SendScreen.jsx";
import TransferDetailScreen from "./screens/TransferDetailScreen.jsx";
import TransfersScreen from "./screens/TransfersScreen.jsx";
import VerifyScreen from "./screens/VerifyScreen.jsx";

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/verify";
  const parts = raw.split("/").filter(Boolean);
  const head = parts[0] || "verify";
  return { path: `/${parts.join("/")}`, head, parts };
}

export default function App() {
  const [token, setToken] = useState(null);
  const [me, setMe] = useState(null);
  const [route, setRoute] = useState(parseHash);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    if (!window.location.hash) window.location.hash = "#/verify";
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function go(path) {
    window.location.hash = `#${path}`;
  }

  function login(nextToken, nextMe) {
    setToken(nextToken);
    setMe(nextMe);
    go("/inventory");
  }

  function logout() {
    setToken(null);
    setMe(null);
    go("/verify");
  }

  const links = useMemo(() => {
    const items = [
      { href: "/verify", label: "Verify" },
      { href: "/labels", label: "Labels" },
      { href: "/products", label: "Provenance" },
    ];
    if (!me) {
      items.push({ href: "/login", label: "Login / Register" });
      return items;
    }
    items.push({ href: "/inventory", label: "Inventory" });
    items.push({ href: "/transfers", label: "Transfers" });
    if (me.organization_type === "MANUFACTURER") items.push({ href: "/register", label: "Register" });
    if (me.organization_type === "MANUFACTURER" || me.organization_type === "DISTRIBUTOR") {
      items.push({ href: "/send", label: "Send" });
    }
    return items;
  }, [me]);

  let page = <VerifyScreen />;
  if (route.head === "login") page = <LoginScreen onLogin={login} />;
  else if (route.head === "labels") page = <LabelsScreen token={token} me={me} />;
  else if (route.head === "register" && token) page = <RegisterScreen token={token} />;
  else if (route.head === "inventory" && token) page = <InventoryScreen token={token} go={go} />;
  else if (route.head === "send" && token && me) page = <SendScreen token={token} me={me} go={go} />;
  else if (route.head === "transfers" && token && me && route.parts[1]) {
    page = <TransferDetailScreen token={token} me={me} transferUid={route.parts[1]} go={go} />;
  } else if (route.head === "transfers" && token && me) page = <TransfersScreen token={token} me={me} go={go} />;
  else if (route.head === "products") {
    page = <ProvenanceScreen token={token} productUid={route.parts[1]} />;
  } else if (["register", "inventory", "send", "transfers"].includes(route.head) && !token) {
    page = <LoginScreen onLogin={login} />;
  }

  return (
    <div className="shell">
      <header className="top">
        <strong>TraceTrust</strong>
        <nav>
          {links.map((link) => (
            <a key={link.href} href={`#${link.href}`} className={route.path.startsWith(link.href) ? "active" : ""}>
              {link.label}
            </a>
          ))}
        </nav>
        {me ? (
          <div className="who">
            <span>
              {me.username} · {me.organization_type}
            </span>
            <button type="button" className="secondary" onClick={logout}>
              Sign out
            </button>
          </div>
        ) : null}
      </header>
      <main>{page}</main>
    </div>
  );
}
