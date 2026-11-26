# Code quality tooling

Use Node 22 and Python 3.12. Install exact npm dependencies with `npm ci --ignore-scripts --no-audit --no-fund`. Install Ruff 0.11.13 in a Python virtual environment and activate it before running the commands (Windows: `.venv\Scripts\Activate.ps1`; Linux/macOS: `source .venv/bin/activate`).

- `npm run format:check`: explicit formatting scope for the initial test/runner
  baseline and the NOTAM/NMS research tools prepared for relocation.
- `npm run format`: format that scope; review the diff. Keep mechanical changes separate from logic or moves.
- `npm run lint`: read-only JavaScript and Python correctness checks; no aviation provider calls.
- `npm run test:node`, `npm run test:scan`: existing offline regression commands. Follow existing browser and release procedures.

The initial format scope avoids application, private staging and acquisition code before equivalent behavior checks exist. Expand in separately reviewed baseline commits. Preserve generated catalogs, snapshots, reference evidence, lockfiles and fixtures. Lint rules are initially conservative. Do not weaken tests or disable failing rules. Record the formatting commit in .git-blame-ignore-revs. CI checks are agent merge gates, not a claim of GitHub-enforced branch protection.

