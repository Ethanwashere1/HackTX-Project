import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "./Avatar";
import "./AppShell.css";

const nav = [
  { to: "/orgs/org_ut", label: "Discover", short: "Home", end: true },
  { to: "/events/evt_hacktx", label: "My events", short: "Events" },
  { to: "/groups/grp_pixel", label: "My teams", short: "Teams" },
  { to: "/requests", label: "Requests", short: "Inbox", badge: 2 },
  { to: "/threads/thr_1", label: "Messages", short: "Chat" },
];

export function AppShell() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    document.body.style.overflow = menuOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [menuOpen]);

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

        <button
          type="button"
          className="shell-org"
          onClick={() => navigate("/orgs/org_ut")}
        >
          <span className="shell-org-mono">UT</span>
          <span className="shell-org-copy">
            <strong>UT Austin</strong>
            <small>Campus community</small>
          </span>
        </button>

        <nav className="shell-nav" aria-label="Main">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `shell-nav-link${isActive ? " is-active" : ""}`
              }
            >
              <span>{item.label}</span>
              {item.badge ? <span className="shell-badge">{item.badge}</span> : null}
            </NavLink>
          ))}
        </nav>

        <div className="shell-spaces">
          <p>Your spaces</p>
          <NavLink to="/orgs/org_ut">UT Austin</NavLink>
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
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `shell-bottom-link${isActive ? " is-active" : ""}`
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
