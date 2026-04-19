# QA Office

Multi-agent AI-powered QA automation platform. Upload test cases or generate them from requirements — the pipeline executes them against your app using Playwright and produces an Excel report.

## Architecture

15-agent pipeline: A0 (generate) → A13 (env check) → A14 (POM build) → A10 (plan) → A12 (seed) → A1 (ingest) → A2 (intent) → A15 (validate) → A3 (locator) → A4 (execute) → A5/A6 (diagnose/heal) → A8 (report) → A10 (reflect) → Synthesis

## Quick Start (Docker)

```bash
cp .env.example .env          # fill in ANTHROPIC_API_KEY, OPENAI_API_KEY
docker-compose up --build
```

Frontend: http://localhost:3005 — Backend: http://localhost:8005

## Quick Start (Local)

**Backend:**
```bash
cd backend
pip install -r requirements.txt
playwright install chromium
python main.py
```

**Frontend:**
```bash
cd frontend
cp .env.example .env.local    # set BACKEND_URL=http://127.0.0.1:8005
npm install
npm run dev
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key (agents A2–A15) |
| `OPENAI_API_KEY` | Yes for scriptless/scripted modes | GPT key for Playwright script generation |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (default: localhost:3005) |
| `BACKEND_URL` | Frontend only | Backend URL seen by Next.js server (default: http://127.0.0.1:8005) |

## Execution Modes

| Mode | Description | Requires |
|---|---|---|
| `page_check` | Checks page loads and content length | Nothing extra |
| `scriptless` | AI generates Playwright steps per test | OpenAI key |
| `scripted` | AI generates full Playwright script | OpenAI key |
