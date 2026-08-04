# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities. Instead,
email the maintainers (see the repository's contact) or use GitHub's private
**"Report a vulnerability"** advisory flow. We aim to acknowledge within a few
days and will credit reporters unless you prefer to remain anonymous.

## Scope & posture

Veriscope is a self-hosted, bring-your-own-key research tool. The security
model and its current controls are documented in
[docs/GOVERNANCE.md](docs/GOVERNANCE.md). In brief:

- **Auth**: Supabase JWT verification (RS256/ES256 via JWKS, audience + issuer
  checked); production refuses to boot with auth disabled.
- **Input**: prompt-injection screening on ingested text, schema-validated LLM
  I/O, an intent guardrail, and bounded uploads.
- **Egress**: an SSRF guard blocks fetches to private/link-local/metadata hosts.
- **Rate limiting & backpressure**: per-subject limits + queue load-shedding.
- **Secrets**: keep them in your `.env` (git-ignored) or a secrets manager —
  never commit real keys. Rotate anything that leaks.

## Supported versions

This is pre-1.0; security fixes land on `main`. Pin a commit if you deploy.
