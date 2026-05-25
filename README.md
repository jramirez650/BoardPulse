# BoardPulse

> "Keeping your board alive — so nothing slips through the cracks."

BoardPulse monitors your team's Jira board, detects stale tickets and key state transitions, and sends AI-generated actionable alerts to Microsoft Teams.

## How it works

1. Connects to Jira and fetches all tickets in the active sprint
2. Detects **stale tickets** (no activity for X days)
3. Detects **PO-accepted tickets** (transitioned from "PO Review" → "PO Accepted")
4. Sends data to **OpenAI** to generate a natural-language summary with urgency classification
5. Posts the alert to a **Microsoft Teams** channel via Incoming Webhook

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Fill in your `.env` file:

| Variable | Description |
|----------|-------------|
| `JIRA_URL` | Your Jira instance URL |
| `JIRA_EMAIL` | Your Atlassian account email |
| `JIRA_API_TOKEN` | Jira API token ([generate here](https://id.atlassian.com/manage-profile/security/api-tokens)) |
| `JIRA_PROJECT` | Jira project key (e.g. `FOR`) |
| `STALE_DAYS_THRESHOLD` | Days without activity before a ticket is flagged (default: `3`) |
| `PO_TRANSITION_FROM` | Source status for PO transition detection (default: `PO Review`) |
| `PO_TRANSITION_TO` | Target status for PO transition detection (default: `PO Accepted`) |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams Incoming Webhook URL |

### 3. Run

```bash
python main.py
```

## Project structure

```
BoardPulse/
├── main.py            # Orchestrator — runs the full pipeline
├── config.py          # Loads settings from .env
├── jira_client.py     # Jira REST API calls
├── rules.py           # Stale ticket + PO transition detection logic
├── ai_summarizer.py   # OpenAI GPT-4o alert generation
├── teams_notifier.py  # Microsoft Teams webhook sender
├── requirements.txt
├── .env.example
└── .gitignore
```

## Team

Hackathon Gallo Pinto 2026 — Group #6  
Andrea Salazar, Jose Ramirez, Alcides Lara, Kimberly Hernandez, Renato Miranda
