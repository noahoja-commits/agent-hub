# Telegram Bot Setup for Agent Hub

The fastest way to command your agents from your phone. Free, no accounts needed beyond Telegram.

## 1. Create the bot (30 seconds)

1. Open Telegram on your phone or desktop
2. Search for **@BotFather** (the official bot creator)
3. Send: `/newbot`
4. Choose a name (e.g. "Agent Hub")
5. Choose a username (e.g. `my_agent_hub_bot`)
6. BotFather replies with your **bot token** — copy it

## 2. Set up on Railway

1. Go to your Railway project variables: https://railway.com/project/494320ef-ba8d-4ca3-8b1d-77c22a24cde6/variables
2. Add: `TELEGRAM_BOT_TOKEN` = the token from BotFather
3. Redeploy (or the variable change triggers auto-deploy)

## 3. Register the webhook

Replace `<TOKEN>` with your bot token and run:
```
curl https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://abyssal-terminal-production.up.railway.app/api/bot/telegram
```

You should see: `{"ok":true,"result":true,"description":"Webhook was set"}`

## 4. Start using it

Open Telegram, find your bot by username, and send:

```
/research search latest AI news
```

Within seconds you'll get a reply with real web search results.

## Commands

| Command | What it does |
|---|---|
| `/research search <query>` | Real-time web search via DuckDuckGo |
| `/research deep_research <query>` | Multi-step research with synthesis |
| `/email check_inbox` | Check your Gmail inbox |
| `/email search_emails <query>` | Search your Gmail |
| `/content write_blog_post <topic>` | AI-generated blog post |
| `/content create_doc <topic>` | AI-generated document |
| `/fixit analyze_code` | Analyze code for bugs |
| `/fixit explain_code` | Explain what code does |

Shorter forms work too: `/search python async`, `/inbox`, etc.

## Troubleshooting

- **Bot doesn't respond**: Check Railway logs. Verify `TELEGRAM_BOT_TOKEN` is set.
- **Webhook not working**: Run the curl command again. Check `BASE_URL` is correct on Railway.
- **"Unknown agent"**: Make sure you use one of: research, email, content, fixit
