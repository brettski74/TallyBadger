# Frontend

React + TypeScript + Vite UI for TallyBadger.

## Local development

```bash
npm install
npm run dev
```

- UI: `http://127.0.0.1:5173`
- API default: `http://127.0.0.1:8080`

To override API base URL:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8080 npm run dev
```

## Tests

```bash
npm test
```

Static frontend test report is written to:

- `../test-results/frontend-vitest.html`

## Current scope

- App shell with logo branding
- Account list/create flow wired to backend API
- UI tests for list render, create success, and duplicate-name error handling
