import { useEffect, useState } from "react";
import { api } from "./api.js";
import Shell from "./components/Shell.jsx";
import AlertsPage from "./pages/AlertsPage.jsx";
import HistoryPage from "./pages/HistoryPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import OverviewPage from "./pages/OverviewPage.jsx";
import ProductsPage from "./pages/ProductsPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import SupplyPage from "./pages/SupplyPage.jsx";
import VerifyPage from "./pages/VerifyPage.jsx";

const TITLES = {
  overview: "Overview",
  products: "Products",
  verify: "QR Verification",
  supply: "Supply Chain",
  alerts: "Alerts",
  history: "Event History",
  settings: "Settings",
};

const PATHS = {
  Overview: "/overview",
  Products: "/products",
  "QR Verification": "/verify",
  "Supply Chain": "/supply",
  Alerts: "/alerts",
  "Event History": "/history",
  Settings: "/settings",
};

function parseHash() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const parts = raw.split("/").filter(Boolean);
  return { head: parts[0] || "", parts };
}

export default function App() {
  const [token, setToken] = useState(null);
  const [me, setMe] = useState(null);
  const [route, setRoute] = useState(parseHash);
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function go(path) {
    window.location.hash = `#${path}`;
  }

  function login(nextToken, nextMe) {
    setToken(nextToken);
    setMe(nextMe);
    go("/overview");
  }

  function logout() {
    setToken(null);
    setMe(null);
    setAlertCount(0);
    go("/login");
  }

  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;
    api("/incidents", { token })
      .then((rows) => {
        if (cancelled) return;
        const open = (rows || []).filter((row) => row.status === "OPEN" || row.status === "UNDER_REVIEW").length;
        setAlertCount(open);
      })
      .catch(() => {
        if (!cancelled) setAlertCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, [token, route.head]);

  if (!token && route.head !== "verify") {
    return <LoginPage onLogin={login} onVerify={() => go("/verify")} />;
  }

  if (!token && route.head === "verify") {
    return (
      <Shell
        me={null}
        active="QR Verification"
        publicMode
        onNavigate={(label) => (label === "QR Verification" ? go("/verify") : go("/login"))}
        onLogout={() => go("/login")}
      >
        <VerifyPage />
      </Shell>
    );
  }

  const page = TITLES[route.head] ? route.head : "overview";

  let body = <OverviewPage token={token} me={me} go={go} />;
  if (page === "products") body = <ProductsPage token={token} me={me} go={go} />;
  else if (page === "verify") body = <VerifyPage />;
  else if (page === "supply") body = <SupplyPage token={token} me={me} transferUid={route.parts[1]} go={go} />;
  else if (page === "alerts") body = <AlertsPage token={token} go={go} />;
  else if (page === "history") body = <HistoryPage token={token} productUid={route.parts[1]} />;
  else if (page === "settings") body = <SettingsPage me={me} onLogout={logout} />;

  return (
    <Shell me={me} active={TITLES[page]} alertCount={alertCount} onNavigate={(label) => go(PATHS[label] || "/overview")} onLogout={logout}>
      {body}
    </Shell>
  );
}
