---
name: cerberus
description: Cerberus Vigilans — Watchdog agent. Uptime monitoring, latency checks, status history, alert testing. Three heads, zero tolerance for downtime.
metadata:
  openclaw:
    requires:
      env: ["AGENT_HUB_TOKEN"]
---

# 🐕 Cerberus — Watchdog Agent (Guardian of the Gates)

Monitors your services and alerts on failure.

## Quick reference

| Action | What it does |
|---|---|
| `check_all` | Check all configured targets |
| `check_one` | Check a specific URL |
| `latency_check` | Measure response times |
| `status_history` | Recent check history |
| `add_target` | Add a monitoring target |
| `alert_test` | Test the alert system |

## How to invoke

```bash
curl -s -X POST "$AGENT_HUB_URL/api/tasks" -H "Authorization: Bearer $AGENT_HUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent":"watchdog","action":"ACTION","params":{...}}'
```

## Examples

Check all targets:
```bash
curl -s -X POST "$AGENT_HUB_URL/api/tasks" -H "Authorization: Bearer $AGENT_HUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent":"watchdog","action":"check_all"}'
```

Check one URL:
```bash
curl -s -X POST "$AGENT_HUB_URL/api/tasks" -H "Authorization: Bearer $AGENT_HUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent":"watchdog","action":"check_one","params":{"url":"https://abyssal-terminal-production.up.railway.app/api/health"}}'
```

Latency comparison:
```bash
curl -s -X POST "$AGENT_HUB_URL/api/tasks" -H "Authorization: Bearer $AGENT_HUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent":"watchdog","action":"latency_check","params":{"urls":["https://google.com","https://github.com"]}}'
```

## Notes
- Default targets include agent-hub health endpoint + google.com
- Configure via WATCH_TARGETS env var (JSON array)
- Alerts via Telegram if TELEGRAM_BOT_TOKEN is set
