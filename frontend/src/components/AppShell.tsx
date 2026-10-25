import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "./Avatar";
import "./AppShell.css";

function orgMono(name: string) {
  const words = name.split(/\s+/).filter(Boolean);
  const caps = name.replace(/[^A-Z]/g, "");
  return (caps.length >= 2 ? caps : words.map((w) => w[0]).join("")).slice(0, 2).toUpperCase();
}

export function AppShell() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [pendingIncoming, setPendingIncoming] = useState(0);

  // Refresh the Requests badge on every navigation (there is no push channel).
  useEffect(() => {
    let live = true;
    api
      .listRequests("incoming")
      .then((items) => {
        if (live) setPendingIncoming(items.filter((r) => r.status === "pending").length);
      })
      .catch(() => {
        /* the badge is best-effort */
      });
    return () => {
      live = false;
    };
  }, [location.pathname]);

  const orgs = me?.orgs ?? [];
  const primary = orgs[0] ?? null;
  const home = primary ? `/orgs/${primary.org_id}` : "/orgs";
  // No "my events", "my teams" or "messages" list exists in the API yet, so the nav links to the
  // org feed (with a joined filter) and the requests inbox, which links to chats and teams.
  const nav = [
    { to: home, label: "Discover", end: true },
    ...(primary ? [{ to: `${home}?joined=1`, label: "My events", end: true }] : []),
    { to: "/requests", label: "Requests", badge: pendingIncoming },
    { to: "/orgs", label: "Organizations", end: true },
  ];

  return (
    <div className="shell">
      <aside className="shell-sidebar">
        <div className="shell-brand">
          <span className="shell-mark" aria-hidden>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM12 14a4.5 4.5 0 0 0-4.5 4.5V20h9v-1.5A4.5 4.5 0 0 0 12 14Z"
                fill="currentColor"
              />
            </svg>
          </span>
          <span>SquadUp</span>
        </div>

        <button
          type="button"
          className="shell-org"
          onClick={() => navigate(home)}
        >
          <span className="shell-org-mono">{primary ? orgMono(primary.name) : "+"}</span>
          <span className="shell-org-copy">
            <strong>{primary?.name ?? "Find an organization"}</strong>
            <small>{primary ? "Campus community" : "Join or create one"}</small>
          </span>
        </button>

        <nav className="shell-nav" aria-label="Main">
          {nav.map((item) => (
            <NavLink
              key={item.label}
              to={item.to}
              end={item.end}
              className={({ isActive }) => {
                // NavLink ignores the query string, so tell Discover and My events apart here.
                const joinedView = new URLSearchParams(location.search).get("joined") === "1";
                const active =
                  isActive &&
                  (item.label === "My events" ? joinedView : item.label === "Discover" ? !joinedView : true);
                return `shell-nav-link${active ? " is-active" : ""}`;
              }}
            >
              <span>{item.label}</span>
              {item.badge ? <span className="shell-badge">{item.badge}</span> : null}
            </NavLink>
          ))}
        </nav>

        <div className="shell-spaces">
          <p>Your spaces</p>
          {orgs.map((o) => (
            <NavLink key={o.org_id} to={`/orgs/${o.org_id}`}>
              {o.name}
            </NavLink>
          ))}
          <NavLink to="/orgs/new">+ Create organization</NavLink>
        </div>

        <div className="shell-foot">
          <NavLink to="/profile">Settings</NavLink>
          <div className="shell-user">
            <Avatar name={me?.name ?? "Guest"} size={34} />
            <div>
              <strong>{me?.name ?? "Guest"}</strong>
              <button type="button" onClick={() => void logout()}>
                Sign out
              </button>
            </div>
          </div>
        </div>
      </aside>

      <div className="shell-main">
        <header className="shell-top">
          <p className="shell-promise">A little connection. A lot of possibility.</p>
          <div className="shell-utils">
            <NavLink to="/requests" className="shell-invites">
              Invitations
            </NavLink>
            <Avatar name={me?.name ?? "Guest"} size={34} />
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  );
}
