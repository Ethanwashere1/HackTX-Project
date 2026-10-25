import { useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import campusHero from "../assets/campus-hero.png";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import "./Login.css";

export function LoginPage() {
  const { me, loginDev, loading } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/orgs/org_ut";

  useEffect(() => {
    if (!loading && me) navigate(next, { replace: true });
  }, [loading, me, navigate, next]);

  async function onGoogle() {
    if (api.useMocks() || params.get("dev") === "1") {
      await loginDev();
      navigate(next);
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
          <span className="su-badge su-badge-teal">Teams · Events · Connections</span>
          <h1>
            Find your squad.
            <br />
            Show up together.
          </h1>
          <p className="login-lede">
            SquadUp connects UT Austin students across structured team events and
            casual 1:1 meetups — matched by mutual interest, not random chance.
          </p>

          <hr className="login-rule" />

          <button type="button" className="su-btn su-btn-google" onClick={() => void onGoogle()}>
            <span className="g">G</span>
            Continue with Google
            <span aria-hidden>→</span>
          </button>
          <p className="login-legal">
            SquadUp uses Google sign-in — no password needed.
            <br />
            By continuing, you agree to our Terms & Privacy Policy.
          </p>

          <div className="login-divider">
            <span />
            <em>Your campus</em>
            <span />
          </div>

          <div className="login-campus">
            <span className="login-ut">UT</span>
            <div>
              <strong>UT Austin — Campus community</strong>
              <p>Hackathon teams, study buddies, photo walks & more.</p>
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
                <span>2</span> Browse events — team challenges or 1:1 meetups
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
            <span className="su-badge su-badge-warm">Team events</span>
            <span className="su-badge su-badge-teal">1:1 connections</span>
            <span className="su-badge su-badge-soft">Casual meetups</span>
          </div>
          <h2>
            Real connections.
            <br />
            Every kind of event.
          </h2>
          <p>
            From hackathon teams to study sessions to Sunday coffee — SquadUp
            matches you with people worth meeting, across every format.
          </p>
          <div className="login-preview">
            <div className="login-avs">
              <span>JL</span>
              <span>PP</span>
              <span>AR</span>
            </div>
            <div>
              <strong>Pixel Pioneers — HackTX Team</strong>
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
