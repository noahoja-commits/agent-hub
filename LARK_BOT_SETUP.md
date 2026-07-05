# Lark Bot Setup for Agent Hub

Deploy a Lark/Feishu bot so you can command your agents from your phone via IM.

## 1. Create a Lark Bot App

1. Go to [Feishu Developer Console](https://open.feishu.cn/app) (or Lark equivalent)
2. Click "Create Custom App" → name it "Agent Hub"
3. Note the **App ID** and **App Secret**

## 2. Configure Event Subscription

1. In your app, go to **Event Subscriptions** → **Request URL**
2. Enter: `https://your-agent-hub.railway.app/api/bot/lark`
3. Lark will send a verification challenge — the agent-hub handles this automatically
4. Subscribe to the event: **im.message.receive_v1** (Receive Message)

## 3. Add Permissions

In **Permissions & Scopes**, add:
- `im:message` — Read messages
- `im:message:send_as_bot` — Send messages as bot
- `im:message:read` — Read message content

Apply and publish.

## 4. Deploy the Bot

1. Go to **App Release** → create a version → publish
2. Make the bot available to your organization (or keep it personal)
3. Open Lark/Feishu, search for your bot, and add it to a chat

## 5. Set Environment Variables on Railway

Add to your Agent Hub deployment:
```
BASE_URL=https://agent-hub.railway.app
LARK_APP_ID=cli_xxxxxxxx
LARK_APP_SECRET=xxxxxxxx
```

## 6. Test It

Send a message to the bot:
```
/agents research search what is the weather today
/agents email check_inbox
/agents content write_blog_post AI trends 2026
```

## Supported Commands

| Command | What it does |
|---|---|
| `/agents email check_inbox` | Summarize your recent inbox emails |
| `/agents email draft_reply <thread_id>` | AI-draft a reply and save as draft |
| `/agents email search_emails <query>` | Search emails by keyword |
| `/agents research search <query>` | Web search with AI summary |
| `/agents research deep_research <query>` | Multi-step research report |
| `/agents research summarize_url <url>` | Fetch and summarize a URL |
| `/agents content create_doc <topic>` | Create a Lark Doc with AI content |
| `/agents content write_blog_post <topic>` | Generate a blog post |
| `/agents content format_report <topic>` | Generate a structured report |
| `/agents fixit analyze_code` | Analyze code for bugs (paste code after) |
| `/agents fixit suggest_fix <error>` | Suggest fix for an error |

The bot responds with the task ID. Results appear in your dashboard.

## Troubleshooting

- **Bot doesn't respond**: Check Railway logs for `/api/bot/lark` requests
- **URL verification fails**: The endpoint returns `{"challenge": "..."}` — verify your Railway app is reachable
- **Bot can't send messages**: Check `im:message:send_as_bot` permission is granted and app is published
- **Tasks created but not executing**: Check `OPENAI_API_KEY` is set in Railway env vars
