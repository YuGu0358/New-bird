# Contributing

## Scope

This project is a monitoring-first trading platform for research and paper-trading workflows.

Please keep these constraints intact:

- No automatic live trading changes unless explicitly discussed.
- Keep broker write actions minimal and easy to audit.
- Prefer small, readable modules over frameworks or abstractions.
- Preserve the browser-based runtime settings flow for deployers.

## Local Setup

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

## Validation

Run these before opening a pull request:

```bash
cd backend
source .venv/bin/activate
python -m unittest discover -s tests
```

```bash
cd frontend
npm run build
```

## Pull Requests

- Explain user-visible behavior changes clearly.
- Mention any new environment variables.
- Add or update tests for backend logic when practical.
- Include screenshots when the UI changes materially.
