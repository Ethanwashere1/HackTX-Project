import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
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
  const location = useLocation();
  const [pendingIncoming, setPendingIncoming] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const onOrgFeed = /^\/orgs\/[^/]+$/.test(location.pathname) && !location.pathname.endsWith("/new");

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    document.body.style.overflow = menuOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [menuOpen]);

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

  // Without an approved org, Discover opens the first org the user can see (its feed page shows a
  // join panel) instead of duplicating the Organizations link.
  const [discoverOrgId, setDiscoverOrgId] = useState<string | null>(null);
  useEffect(() => {
    if (primary) return;
    let live = true;
    api
      .listOrgs()
      .then((list) => {
        const pick = list.find((o) => o.my_status === "pending") ?? list[0];
        if (live && pick) setDiscoverOrgId(pick.org_id);
      })
      .catch(() => {
        /* fall back to /orgs */
      });
    return () => {
      live = false;
    };
  }, [primary]);

  const home = primary
    ? `/orgs/${primary.org_id}`
    : discoverOrgId
      ? `/orgs/${discoverOrgId}`
      : "/orgs";
  // No "my events", "my squads" or "messages" list exists in the API yet, so the nav links to the
  // org feed (with a joined filter) and the requests inbox, which links to chats and squads.
  const nav = [
    { to: home, label: "Discover", short: "Home", end: true },
    ...(primary ? [{ to: `${home}?joined=1`, label: "My events", short: "Events", end: true }] : []),
    { to: "/requests", label: "Requests", short: "Inbox", badge: pendingIncoming },
    { to: "/orgs", label: "Organizations", short: "Orgs", end: true },
  ];

  // NavLink ignores the query string, so tell Discover and My events apart here.
  const isNavActive = (label: string, isActive: boolean) => {
    const joinedView = new URLSearchParams(location.search).get("joined") === "1";
    return (
      isActive && (label === "My events" ? joinedView : label === "Discover" ? !joinedView : true)
    );
  };

  return (
    <div className={`shell${menuOpen ? " is-menu-open" : ""}`}>
      <aside className="shell-sidebar" id="shell-sidebar" aria-label="Sidebar">
        <div className="shell-brand-row">
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
            className="shell-menu-close"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
          >
            ✕
          </button>
        </div>

        {/* Context chip only — not a second "active" nav twin of Discover */}
        <div className="shell-org" aria-label="Current organization">
          <span className="shell-org-mono">{primary ? orgMono(primary.name) : "+"}</span>
          <span className="shell-org-copy">
            <strong>{primary?.name ?? "Find an organization"}</strong>
            <small>{primary ? "Campus community" : "Join or create one"}</small>
          </span>
        </div>

        <nav className="shell-nav" aria-label="Main">
          {nav.map((item) => (
            <NavLink
              key={item.label}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `shell-nav-link${isNavActive(item.label, isActive) ? " is-active" : ""}`
              }
            >
              <span>{item.label}</span>
              {item.badge ? <span className="shell-badge">{item.badge}</span> : null}
            </NavLink>
          ))}
        </nav>

        <div className="shell-spaces">
          <p>Your spaces</p>
          {/* Plain Link — avoids a second aria-current / active twin of Discover */}
          {orgs.map((o) => (
            <Link
              key={o.org_id}
              to={`/orgs/${o.org_id}`}
              className={`shell-space-link${
                onOrgFeed && location.pathname === `/orgs/${o.org_id}` ? " is-current-space" : ""
              }`}
            >
              {o.name}
            </Link>
          ))}
          <NavLink
            to="/orgs/new"
            className={({ isActive }) => `shell-space-link${isActive ? " is-current-space" : ""}`}
          >
            + Create organization
          </NavLink>
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

      {menuOpen ? (
        <button
          type="button"
          className="shell-backdrop"
          aria-label="Close menu overlay"
          onClick={() => setMenuOpen(false)}
        />
      ) : null}

      <div className="shell-main">
        <header className="shell-top">
          <button
            type="button"
            className="shell-menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="shell-sidebar"
            onClick={() => setMenuOpen((v) => !v)}
          >
            Menu
          </button>
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

      <nav className="shell-bottom" aria-label="Mobile">
        {nav.slice(0, 4).map((item) => (
          <NavLink
            key={item.label}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `shell-bottom-link${isNavActive(item.label, isActive) ? " is-active" : ""}`
            }
          >
            <span>{item.short}</span>
            {item.badge ? <i>{item.badge}</i> : null}
          </NavLink>
        ))}
        <NavLink to="/profile" className="shell-bottom-link">
          Profile
        </NavLink>
      </nav>
    </div>
  );
}
