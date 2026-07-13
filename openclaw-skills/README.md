# Agent Hub → OpenClaw Skills

17 demonic OpenClaw skills that wrap the Agent Hub API. Each skill turns your OpenClaw agent into a specialized demon with unique capabilities.

## Install

### Prerequisites
- OpenClaw installed and running
- Agent Hub deployed (https://abyssal-terminal-production.up.railway.app or your own instance)
- `AGENT_HUB_TOKEN` set in your OpenClaw environment

### Quick Install (all 17 skills)

```bash
# Copy all skills to your OpenClaw workspace
cp -r openclaw-skills/* ~/.openclaw/workspace/skills/

# Or install individually to ~/.agents/skills for personal agent scope
cp -r openclaw-skills/* ~/.agents/skills/

# Set required env var (in openclaw.json or shell)
export AGENT_HUB_URL="https://abyssal-terminal-production.up.railway.app"
export AGENT_HUB_TOKEN="replace-with-your-token"
```

### Verify

```bash
openclaw skills list | grep -E "inbox|nova|scribe|forge|echo|pixel|atlas|chronos|mammon|belial|cerberus|janus|fama|thoth|siren|mephisto|hermes"
```

Should show all 17 skills loaded.

## The 17 Demons

### Core Agents (7)

| Skill | Demon | Domain | Key Actions |
|---|---|---|---|
| `inbox` | 📬 Legionem Inbox | Gmail | check_inbox, triage, draft_reply, search, analytics, personality_clone |
| `nova` | 🔭 Scryer of Truth | Research | search (DDG), deep_research, scrape, news_briefing, citations |
| `scribe` | ✨ Scriba Sanguinis | Content | docs, slides, blogs, reports, code gen, SEO, game_master |
| `forge` | ⚒️ Malleus Codicis | Code Fixes | analyze, suggest_fix, review_pr, security_audit, tests, docs |
| `echo-dev` | 💀 Daemon Forge | Dev | write_code, run_code, debug, scaffold_project, generate_api |
| `pixel` | 🎨 Pictor Inferni | Images | DALL-E/SVG generation, logos, illustrations, variations |
| `atlas` | 🧠 Atlas Abyssalis | Orchestrator | natural language, plan_and_execute, agent duels |

### Expanded Agents (10)

| Skill | Demon | Domain | Key Actions |
|---|---|---|---|
| `chronos` | ⏳ Chronos Aeternum | Calendar | today, week, find_slot, create_event, upcoming |
| `mammon` | 💰 Mammon Avarus | Finance | stock_price, crypto, market_summary, portfolio, currency |
| `belial` | 📞 Belial Negotiator | CRM/Sales | cold_call, deal_analysis, pitch_deck, lead_qualifier |
| `cerberus` | 🐕 Cerberus Vigilans | Watchdog | check_all, latency_check, add_target, alert_test |
| `janus` | 🗄️ Janus Bifrons | FileOps | search_files, backup, organize, disk_usage |
| `fama` | 📢 Fama Volans | Social | create_post, thread, hashtag_strategy, bio |
| `thoth` | 📊 Thoth Scriba | Database | query_csv, schema_design, generate_sql, csv_to_json |
| `siren` | 🎙️ Siren Cantrix | Audio | transcribe, meeting_summary, podcast_script |
| `mephisto` | 📄 Mephisto Contractus | PDF | generate_contract, create_invoice, extract_text |
| `hermes` | 🌐 Hermes Interpres | Translation | translate, detect, localize, code_comments |

## Usage in OpenClaw

Once installed, invoke any skill by name:

```
/skill inbox — check my email
/skill nova — search for Python 3.14 features
/skill mammon — what's AAPL trading at?
/skill atlas — find the latest AI news and write a blog post about it
```

Or just ask naturally — OpenClaw will match the right skill based on the description.

Each skill uses `exec` to call the Agent Hub REST API via curl. All tasks run asynchronously — the skill creates a task, polls for completion, and returns the result.

## Configuration

Required env vars (set in `openclaw.json` or shell):

```json5
{
  "env": {
    "AGENT_HUB_URL": "https://abyssal-terminal-production.up.railway.app",
    "AGENT_HUB_TOKEN": "replace-with-your-token"
  }
}
```

For multi-agent setups, use per-agent allowlists:

```json5
{
  "agents": {
    "defaults": {
      "skills": ["atlas"]
    },
    "list": [
      { "id": "researcher", "skills": ["nova", "thoth", "hermes"] },
      { "id": "writer", "skills": ["scribe", "fama", "mephisto"] },
      { "id": "devops", "skills": ["forge", "echo-dev", "cerberus", "janus"] },
      { "id": "business", "skills": ["inbox", "chronos", "mammon", "belial"] }
    ]
  }
}
```

Now you have 4 OpenClaw agents, each with a specialized demon loadout.
