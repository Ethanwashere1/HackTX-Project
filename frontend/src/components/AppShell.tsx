import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "./Avatar";
import "./AppShell.css";

const nav = [
  { to: "/orgs/org_ut", label: "Discover", end: true },
  { to: "/events/evt_hacktx", label: "My events" },
  { to: "/groups/grp_pixel", label: "My teams" },
  { to: "/requests", label: "Requests", badge: 2 },
  { to: "/threads/thr_1", label: "Messages" },
];

export function AppShell() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

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
