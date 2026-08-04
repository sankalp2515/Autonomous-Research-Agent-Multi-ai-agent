---
name: Bug report
about: Something isn't working as expected
title: "[bug] "
labels: bug
---

**What happened**
A clear description of the bug.

**Steps to reproduce**
1. …
2. …

**Expected behavior**
What you expected instead.

**Environment**
- OS:
- Running via: [ docker compose | local venv ]
- ML enabled (`ML_NLI_ENABLED`): [ yes | no ]

**Logs**
For pipeline issues, paste the last ~15 lines of the worker log (the heartbeat
+ per-call timings make most failures obvious). Scrub any secrets.
