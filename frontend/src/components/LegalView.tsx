// Public privacy / terms pages. These are honest, plain-language starter
// documents that describe how Veriscope actually works today (Supabase auth,
// per-project corpus, arXiv/Semantic Scholar sourcing). They are NOT a
// substitute for review by counsel before you take real customers or payment —
// treat them as a solid first draft to hand a lawyer.

const CONTACT = "support@veriscope.app";
const UPDATED = "August 2026";

export default function LegalView({ doc }: { doc: "privacy" | "terms" }) {
  return (
    <div className="shared-page">
      <div className="shared-topbar">
        <a className="landing-brand" href="#/">
          <span className="logo landing-logo">V</span><span>Veriscope</span>
        </a>
        <a className="btn btn-ghost" href="#/">Open Veriscope →</a>
      </div>
      <div className="legal">
        {doc === "privacy" ? <Privacy /> : <Terms />}
        <footer className="legal-foot">
          <span>Last updated {UPDATED}.</span>
          <span>
            Questions? <a href={`mailto:${CONTACT}`}>{CONTACT}</a> ·{" "}
            {doc === "privacy" ? <a href="#/legal/terms">Terms</a> : <a href="#/legal/privacy">Privacy</a>}
          </span>
        </footer>
      </div>
    </div>
  );
}

function Privacy() {
  return (
    <article>
      <h1>Privacy Policy</h1>
      <p className="legal-lead">
        This policy explains what Veriscope collects, why, and the choices you have.
        We keep it short because the product collects little.
      </p>

      <h2>What we collect</h2>
      <ul>
        <li><b>Account data.</b> If sign-in is enabled, we store your email address and an
          authentication token via our auth provider (Supabase). We never see your password.</li>
        <li><b>Your research content.</b> Projects, uploaded PDFs, imported references, notes,
          and the reports generated for you. This is stored so the product works and is visible
          only to your account.</li>
        <li><b>Operational logs.</b> Basic request and error information needed to keep the
          service running and to diagnose crashes.</li>
      </ul>

      <h2>What we don’t do</h2>
      <ul>
        <li>We do not sell your data.</li>
        <li>We do not use your research content to train third-party models.</li>
        <li>We do not run advertising trackers.</li>
      </ul>

      <h2>Third parties</h2>
      <p>
        To function, Veriscope shares data with a small number of processors: our authentication
        provider (Supabase), our hosting/error-reporting infrastructure, and the scholarly
        sources we query on your behalf (arXiv, Semantic Scholar). Search queries you run are sent
        to those sources to retrieve papers.
      </p>

      <h2>Data retention &amp; deletion</h2>
      <p>
        Your content persists until you delete it or close your account. Removed sources keep an
        auditable tombstone so previously cited claims remain traceable. To delete your account and
        associated data, email <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.
      </p>

      <h2>Cookies &amp; local storage</h2>
      <p>
        We use strictly necessary storage to keep you signed in. We do not set non-essential or
        advertising cookies, so no consent banner is required.
      </p>

      <h2>Contact</h2>
      <p>Reach us at <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.</p>
    </article>
  );
}

function Terms() {
  return (
    <article>
      <h1>Terms of Service</h1>
      <p className="legal-lead">
        By using Veriscope you agree to these terms. They’re written to be readable, not to trick you.
      </p>

      <h2>The service</h2>
      <p>
        Veriscope is a research workspace that searches scholarly literature and drafts reports in
        which every claim is grounded in a real source. It is a research aid, not professional,
        legal, medical, or financial advice, and it can still be wrong — verify anything you rely on.
      </p>

      <h2>Your content</h2>
      <p>
        You retain ownership of the PDFs, notes, and questions you bring to Veriscope. You grant us
        the limited rights needed to store and process that content to provide the service to you.
      </p>

      <h2>Acceptable use</h2>
      <ul>
        <li>Don’t upload content you don’t have the right to use.</li>
        <li>Don’t attempt to disrupt, reverse-engineer, or overload the service.</li>
        <li>Don’t use Veriscope to produce or launder deliberately false claims.</li>
      </ul>

      <h2>Availability &amp; changes</h2>
      <p>
        The service is provided “as is,” without warranty. We may update, suspend, or discontinue
        features, and we’ll make reasonable efforts to communicate material changes.
      </p>

      <h2>Limitation of liability</h2>
      <p>
        To the extent permitted by law, Veriscope is not liable for indirect or consequential damages
        arising from your use of the service.
      </p>

      <h2>Contact</h2>
      <p>Questions about these terms? Email <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.</p>
    </article>
  );
}
