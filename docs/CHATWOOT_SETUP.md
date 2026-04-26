# Chatwoot Setup — Self-hosted Multi-channel Inbox for Agents

> Step-by-step guide to deploy Chatwoot for Etnia, connect it to WhatsApp / Instagram / Facebook, and integrate it with the bot so the bot pre-qualifies leads and human agents take over inside Chatwoot.

---

## 0. What you'll have at the end

- A self-hosted Chatwoot instance (Docker Compose) running on a small VPS, total cost ~$5–10/month.
- Three channel inboxes: WhatsApp, Instagram, Facebook Messenger.
- Agent accounts for the Etnia sales team to handle conversations from one screen.
- The bot connected as an **Agent Bot** so it can reply on behalf of agents until it triggers a handoff.
- A clear flow: customer messages → bot qualifies in the background → on handoff, conversation appears in the human agents' inbox with full context.

Total time: **~3–5 hours** the first time, mostly Docker setup + channel verification.

---

## 1. Decide hosting

### Option A — Self-hosted (recommended)
- A $5/month VPS at Hetzner, DigitalOcean, or Vultr handles a small team comfortably.
- You own the data, no per-agent fees, unlimited conversations.
- You maintain it (updates, backups, SSL renewal).
- Recommended specs: **2 vCPU, 4 GB RAM, 40 GB SSD**. 2 GB RAM works but is tight.

### Option B — Chatwoot Cloud (managed)
- Free tier: 2 agents, limited features.
- Paid: ~$19/agent/month and up.
- Skip the ops work, lose some control.
- For Etnia (small team, full control desired), self-hosted is the obvious pick.

This guide covers **self-hosted**.

---

## 2. Provision the VPS

Pick a provider and create an Ubuntu 22.04 droplet/server.

### 2.1 First-time server setup
SSH in as root, then:

```bash
# Update
apt update && apt upgrade -y

# Create a non-root user
adduser etnia
usermod -aG sudo etnia

# Install Docker + Compose
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin

# Add etnia to docker group
usermod -aG docker etnia

# Firewall: SSH + HTTP + HTTPS only
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

Log out, log back in as `etnia`.

### 2.2 Point a domain at the server
You need a public hostname (e.g., `crm.etniaviajes.com.ar`). Add an A record pointing to the VPS IP. SSL setup in §4 needs this resolved.

---

## 3. Deploy Chatwoot

### 3.1 Clone the official Docker setup
```bash
mkdir -p ~/chatwoot && cd ~/chatwoot
wget -O docker-compose.yml https://raw.githubusercontent.com/chatwoot/chatwoot/master/docker-compose.production.yaml
wget -O .env https://raw.githubusercontent.com/chatwoot/chatwoot/master/.env.example
```

### 3.2 Edit `.env`

Critical settings to change:
```env
SECRET_KEY_BASE=                      # generate with: openssl rand -hex 64
FRONTEND_URL=https://crm.etniaviajes.com.ar
INSTALLATION_NAME=Etnia CRM
DEFAULT_LOCALE=es

# Postgres
POSTGRES_HOST=postgres
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=                    # generate with: openssl rand -hex 24
POSTGRES_DATABASE=chatwoot

# Redis
REDIS_URL=redis://redis:6379

# Email (use a real SMTP for password resets, Mailgun/SES/Postmark)
MAILER_SENDER_EMAIL=Etnia CRM <crm@etniaviajes.com.ar>
SMTP_ADDRESS=smtp.mailgun.org
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...

# Storage (start with local disk, move to S3 later)
ACTIVE_STORAGE_SERVICE=local

# Disable signups (so random people can't register)
ENABLE_ACCOUNT_SIGNUP=false
```

### 3.3 First boot — initialize the database

```bash
docker compose run --rm rails bundle exec rails db:chatwoot_prepare
docker compose up -d
```

Wait ~30 seconds, then check:
```bash
docker compose ps           # all services should be "Up"
docker compose logs -f rails | head -50
```

At this point Chatwoot is listening on `localhost:3000` inside the server.

---

## 4. Put a reverse proxy + HTTPS in front

### 4.1 Install Caddy (simplest TLS — auto-renews Let's Encrypt)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

### 4.2 Configure Caddy

Edit `/etc/caddy/Caddyfile`:
```caddy
crm.etniaviajes.com.ar {
    reverse_proxy localhost:3000
    encode gzip
}
```

Reload:
```bash
sudo systemctl reload caddy
```

Visit `https://crm.etniaviajes.com.ar` — you should see the Chatwoot setup page.

### 4.3 Create the super-admin account
On the setup page, fill in name, email, password. This is the owner account; create individual agent accounts inside the app afterwards.

---

## 5. Connect channels

In Chatwoot UI: **Settings → Inboxes → Add Inbox**.

### 5.1 Facebook Messenger inbox
1. Pick **Facebook**.
2. Click **Connect with Facebook** — OAuth flow opens.
3. Log in with the FB account that admins the Etnia Page.
4. Approve the requested permissions (Chatwoot needs `pages_messaging`, `pages_manage_metadata` on its own Meta app — this is Chatwoot's app, not yours, you don't need to manage it).
5. Pick the Etnia Page from the list → confirm.
6. Add agents to the inbox.

Done. Test by messaging the Page from a personal account; the message appears in Chatwoot.

> **Important:** if you also want the bot's `/webhooks/meta` endpoint to receive these messages, that won't work — a Page can only be subscribed to **one** webhook URL at a time. You have two options:
> - **Option 1:** Bot logic moves entirely behind Chatwoot's Agent Bot interface (recommended). Chatwoot becomes the only thing subscribed to the Page; the bot reacts via Chatwoot's webhook (§6).
> - **Option 2:** Subscribe the Page to your own bot's webhook, and use Chatwoot's API channel instead of native FB integration. More work, no real upside.

Use Option 1. Detailed in §6.

### 5.2 Instagram inbox
1. **Settings → Inboxes → Add Inbox → Instagram**.
2. OAuth flow with the same Facebook account that admins the Page.
3. Pick the linked Instagram Business account.
4. Add agents.

Same caveat as FB: Chatwoot owns the webhook.

### 5.3 WhatsApp inbox
WhatsApp is more involved than FB/IG. Three sub-options inside Chatwoot:

#### 5.3.1 WhatsApp Cloud API (official, recommended for production)
- Free tier: 1,000 user-initiated conversations/month from Meta.
- Requires: Meta Business Account + verified business + phone number not currently on regular WhatsApp.
- In Chatwoot: **Add Inbox → WhatsApp → WhatsApp Cloud (Meta)** → enter Phone Number ID, Business Account ID, Access Token (all from your own Meta WhatsApp app).
- Webhook URL Chatwoot gives you → paste into the WhatsApp app's webhook config in Meta Dev Dashboard.

#### 5.3.2 360Dialog (paid BSP, ~$5/month + per-message)
- Easier onboarding than Cloud API.
- Chatwoot has a native 360Dialog integration.

#### 5.3.3 WPPConnect / Baileys (current setup, unofficial)
- This is what `app/utils/whatsapp.py` currently uses.
- **Not officially supported** by WhatsApp; risk of number ban.
- Fine for prototyping. **Migrate to Cloud API before production scale.**
- Connect via Chatwoot's "API" channel type and bridge through your existing WPP adapter.

**Recommendation:** for production, use **WhatsApp Cloud API**. Keep WPPConnect only during development. The migration is straightforward — same webhook event structure, different sender API.

---

## 6. Connect the bot as an Agent Bot

Chatwoot's **Agent Bot** is a native concept: a bot that receives every new conversation in an inbox and replies until it explicitly hands off to a human.

### 6.1 Create the Agent Bot in Chatwoot

**Settings → Integrations → Agent Bots → Add Agent Bot**:
- Name: `Etnia Qualifier Bot`.
- Outgoing URL: `https://your-bot-domain/webhooks/chatwoot`
- Copy the **Bot Access Token** Chatwoot generates.

Then assign the bot to each inbox:
**Settings → Inboxes → [inbox] → Configuration → Agent Bot → select Etnia Qualifier Bot**.

### 6.2 What Chatwoot sends to your bot

Every message in any of those inboxes triggers a `POST` to your `outgoing URL`:

```json
{
  "event": "message_created",
  "id": 12345,
  "content": "Hola, vi su anuncio de Aruba",
  "message_type": "incoming",
  "conversation": {
    "id": 678,
    "inbox_id": 1,
    "status": "open",
    "channel": "Channel::FacebookPage",
    "contact_inbox": {
      "source_id": "USER_PSID_OR_PHONE",
      "contact_id": 999
    }
  },
  "sender": {
    "id": 999,
    "name": "Juan Pérez",
    "phone_number": "+5491100000000"   // for WhatsApp
  }
}
```

Your bot's `/webhooks/chatwoot` handler:
1. Verify the request comes from Chatwoot (header `Api-Access-Token` matches the Bot Access Token).
2. Skip if `message_type != "incoming"` or sender is the bot itself.
3. Run the existing `ChatbotService.process_message` flow.
4. Reply via Chatwoot's API (§6.3), not via the channel directly — Chatwoot routes the reply to the right channel for you.

### 6.3 Sending replies via Chatwoot API

```bash
curl -X POST \
  "https://crm.etniaviajes.com.ar/api/v1/accounts/1/conversations/678/messages" \
  -H "api_access_token: $BOT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "¡Hola! Somos Etnia Viajes ✨",
    "message_type": "outgoing",
    "private": false
  }'
```

`private: true` makes the message an internal note (visible to agents but not to the customer). Useful for the bot to leave qualification context for the agent before handing off.

### 6.4 Triggering the handoff to a human

When the bot's existing logic decides it's a handoff state (`HANDOFF_WITH_OFFER`, etc.):

1. **Leave a private note** with the qualification summary:
   ```json
   {
     "content": "🤖 Lead calificado:\n- Destino: Aruba\n- Salida: Córdoba\n- 2 adultos, 1 menor\n- Fecha: agosto",
     "message_type": "outgoing",
     "private": true
   }
   ```

2. **Stop being the bot** — toggle the conversation status / unassign the bot:
   ```bash
   curl -X POST \
     "https://crm.etniaviajes.com.ar/api/v1/accounts/1/conversations/678/toggle_status" \
     -H "api_access_token: $BOT_ACCESS_TOKEN"
   # OR assign to a specific agent:
   curl -X POST \
     "https://crm.etniaviajes.com.ar/api/v1/accounts/1/conversations/678/assignments" \
     -H "api_access_token: $BOT_ACCESS_TOKEN" \
     -d '{"assignee_id": <agent_id>}'
   ```

3. **Add a label** so the agent dashboard can filter:
   ```bash
   curl -X POST \
     "https://crm.etniaviajes.com.ar/api/v1/accounts/1/conversations/678/labels" \
     -H "api_access_token: $BOT_ACCESS_TOKEN" \
     -d '{"labels": ["handoff", "destino-aruba"]}'
   ```

After this, Chatwoot routes new incoming messages on this conversation to assigned agents instead of the bot.

### 6.5 Letting the agent "release back to bot"

Convention: when an agent applies a label `bot-takeover`, your backend listens for the `conversation_updated` Chatwoot webhook event and re-attaches the bot. Or simpler: don't allow this; once a human is in, they finish the conversation.

---

## 7. Agent setup

### 7.1 Create agent accounts
**Settings → Agents → Add Agents** → enter email → Chatwoot sends them an invite to set their password.

Recommended roles:
- **Administrator:** you, 1–2 trusted leads.
- **Agent:** sales reps. Can see and reply to conversations assigned to them or in inboxes they're members of.

### 7.2 Teams (optional, useful at 5+ agents)
**Settings → Teams** → create a "Sales" team → add agents → assign teams to inboxes. Lets you do round-robin or load-based assignment.

### 7.3 Auto-assignment
**Settings → Inboxes → [inbox] → Collaborators → Conversation Assignment**:
- **Round Robin** — fair distribution.
- **Balanced** — assigns to the agent with fewest open conversations.

Pick one.

### 7.4 Canned responses
**Settings → Canned Responses** — pre-typed replies agents can insert with `/<shortcode>`. Save common sales responses here so agents don't retype.

---

## 8. Backups and maintenance

### 8.1 Database backup (do this from day 1)
```bash
# In ~/chatwoot
docker compose exec postgres pg_dump -U postgres chatwoot | gzip > /backups/chatwoot-$(date +%F).sql.gz
```

Schedule via cron (`crontab -e`):
```
0 3 * * * cd /home/etnia/chatwoot && docker compose exec -T postgres pg_dump -U postgres chatwoot | gzip > /backups/chatwoot-$(date +\%F).sql.gz
```

Sync `/backups` offsite (rclone to Google Drive or S3 — don't keep them only on the same VPS).

### 8.2 Updates
Every 1–2 months:
```bash
cd ~/chatwoot
docker compose pull
docker compose run --rm rails bundle exec rails db:migrate
docker compose up -d
```

Always read the [Chatwoot release notes](https://github.com/chatwoot/chatwoot/releases) for breaking changes.

### 8.3 File storage
After ~6 months, local disk usage from media attachments grows. Migrate to S3-compatible storage (Backblaze B2 is cheap):
```env
ACTIVE_STORAGE_SERVICE=amazon
S3_BUCKET_NAME=etnia-chatwoot-media
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-005
S3_ENDPOINT=https://s3.us-east-005.backblazeb2.com   # for B2
```

---

## 9. Relationship to the bot's own database

Even with Chatwoot in place, **keep the Postgres CRM schema** from `CODE_REVIEW.md` §5.1.

Why both:
- **Chatwoot owns** the operational inbox (conversations, agent activity, message history, attachments). Don't duplicate this.
- **Your Postgres owns** the qualification/sales pipeline (offers shown, leads scored, deals progressed, analytics). Chatwoot is bad at custom business data.

Keep them in sync via Chatwoot's webhooks:
- `conversation_created` → create matching `Conversation` row in Postgres with the Chatwoot conversation ID.
- `message_created` → don't mirror the message body (lives in Chatwoot), but do update `last_inbound_at`, run extraction, update qualification fields.
- `conversation_resolved` → mark deal stage in Postgres.

This keeps Chatwoot lean and your reporting flexible.

---

## 10. Production checklist

- [ ] Domain points to VPS, HTTPS works.
- [ ] SMTP configured (test with a password reset email).
- [ ] `ENABLE_ACCOUNT_SIGNUP=false` in `.env`.
- [ ] At least one Administrator + 2 Agent accounts created.
- [ ] All three inboxes connected (WA + IG + FB).
- [ ] Agent Bot configured and assigned to all inboxes.
- [ ] Bot's `/webhooks/chatwoot` endpoint live, signed-token verification working.
- [ ] Test conversation flows end-to-end on each channel: bot answers, hands off, agent sees private note + summary.
- [ ] Daily DB backup running, restore tested at least once.
- [ ] Monitoring: uptime check (UptimeRobot free) on `https://crm.etniaviajes.com.ar`.
- [ ] Documented runbook for "Chatwoot is down": where to log in, how to restart Docker stack, where backups are.

---

## Reference links

- Chatwoot self-hosted docs: <https://www.chatwoot.com/docs/self-hosted>
- Agent Bots overview: <https://www.chatwoot.com/docs/product/agent-bots/agent-bots-overview>
- Chatwoot API reference: <https://www.chatwoot.com/developers/api/>
- Channel setup guides: <https://www.chatwoot.com/docs/product/channels/overview>
- WhatsApp Cloud API integration: <https://www.chatwoot.com/docs/product/channels/whatsapp/whatsapp-cloud>
