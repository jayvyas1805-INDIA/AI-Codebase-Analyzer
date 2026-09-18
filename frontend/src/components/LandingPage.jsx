/**
 * Marketing entry point. Shown before login — sells what the tool does
 * and hands off to LoginPage via onGetStarted().
 */
export default function LandingPage({ onGetStarted }) {
  return (
    <div className="landing">
      <header className="landing-nav">
        <span className="landing-nav__brand">
          <span className="landing-nav__dot" />
          React Codebase Analyzer
        </span>
        <button className="secondary-button" onClick={onGetStarted}>
          Log in
        </button>
      </header>

      <section className="landing-hero">
        <div className="landing-hero__copy">
          <h1>
            Find the CSS that's
            <br />
            quietly breaking your build.
          </h1>
          <p className="landing-hero__subtitle">
            Upload a zipped React project and get a full map of class name
            conflicts, dead styles, and undefined classNames — with an AI
            explanation for every issue it finds.
          </p>
          <div className="landing-hero__actions">
            <button className="analyze-button" onClick={onGetStarted}>
              Analyze your project
            </button>
            <span className="landing-hero__hint">No install — runs in your browser</span>
          </div>
        </div>

        <div className="landing-hero__visual" aria-hidden="true">
          <div className="scan-window">
            <div className="scan-window__bar">
              <span className="scan-window__dot" />
              <span className="scan-window__dot" />
              <span className="scan-window__dot" />
              <span className="scan-window__title">Navbar.css</span>
            </div>
            <div className="scan-window__body">
              <div className="scan-line">
                <span className="scan-line__num">12</span>
                <span className="scan-line__code">.nav-link {"{"}</span>
              </div>
              <div className="scan-line scan-line--conflict">
                <span className="scan-line__num">13</span>
                <span className="scan-line__code">  color: var(--muted);</span>
                <span className="scan-line__flag">conflict</span>
              </div>
              <div className="scan-line">
                <span className="scan-line__num">14</span>
                <span className="scan-line__code">{"}"}</span>
              </div>
              <div className="scan-line scan-line--unused">
                <span className="scan-line__num">18</span>
                <span className="scan-line__code">.nav-link--legacy {"{"} ... {"}"}</span>
                <span className="scan-line__flag scan-line__flag--unused">unused</span>
              </div>
              <div className="scan-line">
                <span className="scan-line__num">24</span>
                <span className="scan-line__code">.nav-cta {"{"}</span>
              </div>
              <div className="scan-line scan-line--undefined">
                <span className="scan-line__num">·</span>
                <span className="scan-line__code">Navbar.jsx uses "nav-ctaa"</span>
                <span className="scan-line__flag scan-line__flag--undefined">undefined</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-features">
        <div className="feature-card">
          <h3>Class conflict detection</h3>
          <p>
            Catches selectors that quietly override each other across files,
            with a side-by-side diff of exactly what's colliding.
          </p>
        </div>
        <div className="feature-card">
          <h3>Unused &amp; undefined styles</h3>
          <p>
            Flags CSS rules nothing renders anymore, and classNames in your
            JSX that don't map to any rule at all.
          </p>
        </div>
        <div className="feature-card">
          <h3>AI explanations</h3>
          <p>
            Ask about any issue in plain language and get a recommendation
            for how to fix it, grounded in your actual code.
          </p>
        </div>
      </section>

      <footer className="landing-footer">
        <span>Built for React projects. Nothing leaves your session.</span>
      </footer>
    </div>
  );
}
