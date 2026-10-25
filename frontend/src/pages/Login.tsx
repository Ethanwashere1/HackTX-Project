import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import campusHero from "../assets/campus-hero.png";
import { api, SEED_USERS, type SeedUser } from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import { useAuth } from "../auth/AuthContext";
import "./Login.css";

export function LoginPage() {
  const { me, loginDev, loading } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/";
  const oauthError = params.get("error");
  const [error, setError] = useState<string | null>(
    oauthError === "oauth_access_denied" ? "Google sign-in was cancelled." : oauthError,
  );
  const [busy, setBusy] = useState<string | null>(null);
  // The dev-login picker: only under `vite dev` or in mock mode. The backend also refuses
  // dev-login unless APP_ENV is local/test and DEV_LOGIN=1.
  const showDevLogin = import.meta.env.DEV || api.useMocks();

  useEffect(() => {
    if (!loading && me) navigate(next, { replace: true });
  }, [loading, me, navigate, next]);

  async function onDevLogin(user: SeedUser) {
    setBusy(user.email);
    setError(null);
    try {
      await loginDev(user);
      navigate(next);
    } catch (e) {
      setError(
        errorMessage(e) +
          (e instanceof ApiError && e.status === 404
            ? " (start the backend with APP_ENV=local DEV_LOGIN=1)"
            : ""),
      );
    } finally {
      setBusy(null);
    }
  }

  function onGoogle() {
    if (api.useMocks()) {
      void onDevLogin(SEED_USERS[0]);
      return;
    }
    window.location.href = api.googleLoginUrl(next);
  }

  return (
    <div className="login">
      <section className="login-panel su-fade-up">
        <div className="login-brand">
          <span className="login-mark" aria-hidden />
          <strong>SquadUp</strong>
        </div>

        <div className="login-content">
          <span className="su-badge su-badge-teal">Squads · Events · Connections</span>
          <h1>
            Find your squad.
            <br />
            Show up together.
          </h1>
          <p className="login-lede">
            SquadUp connects UT Austin students across structured squad events and
            casual 1:1 meetups — matched by mutual interest, not random chance.
          </p>

          <hr className="login-rule" />

          <button type="button" className="su-btn su-btn-google" onClick={onGoogle}>
            <span className="g">G</span>
            Continue with Google
            <span aria-hidden>→</span>
          </button>
          <p className="login-legal">
            SquadUp uses Google sign-in — no password needed.
            <br />
            By continuing, you agree to our Terms & Privacy Policy.
          </p>
          {error ? (
            <p role="alert" style={{ color: "var(--su-danger)", margin: "0.5rem 0 0" }}>
              {error}
            </p>
          ) : null}

          {showDevLogin ? (
            <div className="su-card" style={{ padding: "0.85rem", marginTop: "1rem", boxShadow: "none" }}>
              <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: "var(--su-text-muted)" }}>
                Dev login (seed users)
              </p>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {SEED_USERS.map((u) => (
                  <button
                    key={u.email}
                    type="button"
                    className="su-btn su-btn-secondary"
                    disabled={busy !== null}
                    title={u.email}
                    onClick={() => void onDevLogin(u)}
                  >
                    {busy === u.email ? "Signing in…" : u.name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="login-divider">
            <span />
            <em>Your campus</em>
            <span />
          </div>

          <div className="login-campus">
            <span className="login-ut">UT</span>
            <div>
              <strong>UT Austin — Campus community</strong>
              <p>Hackathon squads, study buddies, photo walks & more.</p>
            </div>
            <span className="su-badge su-badge-teal">Active</span>
          </div>

          <div className="login-steps">
            <p>How it works</p>
            <ol>
              <li>
                <span>1</span> Sign in and complete your interest profile
              </li>
              <li>
                <span>2</span> Browse events — squad challenges or 1:1 meetups
              </li>
              <li>
                <span>3</span> Get matched — both sides accept before anything starts
              </li>
            </ol>
          </div>
        </div>

        <footer className="login-foot">
          <span>© 2026 SquadUp</span>
          <Link to={next}>Next: Explore UT Austin →</Link>
        </footer>
      </section>

      <section
        className="login-story su-fade-up-delay"
        style={{ backgroundImage: `url(${campusHero})` }}
      >
        <div className="login-story-scrim" />
        <div className="login-story-top">
          <span className="su-badge su-badge-soft">Austin, Texas · UT Austin</span>
          <span className="su-badge su-badge-soft">Campus community</span>
        </div>
        <div className="login-story-body">
          <div className="login-pills">
            <span className="su-badge su-badge-warm">Squad events</span>
            <span className="su-badge su-badge-teal">1:1 connections</span>
            <span className="su-badge su-badge-soft">Casual meetups</span>
          </div>
          <h2>
            Real connections.
            <br />
            Every kind of event.
          </h2>
          <p>
            From hackathon squads to study sessions to Sunday coffee — SquadUp
            matches you with people worth meeting, across every format.
          </p>
          <div className="login-preview">
            <div className="login-avs">
              <span>JL</span>
              <span>PP</span>
              <span>AR</span>
            </div>
            <div>
              <strong>Pixel Pioneers — HackTX Squad</strong>
              <p>3 of 4 members matched · Backend, ML & product</p>
            </div>
            <em>1 spot left</em>
          </div>
          <ul>
            <li>✓ Pick your vibe</li>
            <li>✓ Mutual consent to match</li>
            <li>✓ Show up, meet in person</li>
          </ul>
        </div>
      </section>
    </div>
  );
}
