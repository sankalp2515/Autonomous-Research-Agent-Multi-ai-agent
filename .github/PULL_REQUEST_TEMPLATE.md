## What & why

Briefly describe the change and the problem it solves. Link the issue it closes.

## Checklist

- [ ] `cd backend && pytest` passes
- [ ] `cd backend && ruff check app` is clean
- [ ] `cd frontend && npm run build` passes (type-check + build)
- [ ] I did **not** bypass the verification gate — any new claim surface routes
      through `app/verification/gate.py`
- [ ] Evidence classes stay separated (scholarly vs practitioner never blended)
- [ ] Added/updated tests for behavior changes (especially trust-critical ones)

## Notes for reviewers

Anything non-obvious, trade-offs, or follow-ups.
