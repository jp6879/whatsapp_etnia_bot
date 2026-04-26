# Meta Developer App Setup — Instagram & Facebook Messaging

> Step-by-step guide to wire your existing Meta Developer App for Instagram DMs and Facebook Messenger, sending events into the bot's `/webhooks/meta` endpoint.

---

## 0. What you'll have at the end

- One Meta App with **Messenger** + **Instagram** products enabled.
- A Facebook Page connected to an Instagram Business account.
- Long-lived Page Access Token issued via a System User (no personal-login dependency).
- Webhook URL receiving signed `messages` events for both FB and IG.
- Dev-mode testing working end-to-end with your own accounts.
- App Review submission ready (when you decide to go to production).

Total time: **2–4 hours** the first time, mostly waiting for Facebook UI to do things.

---

## 1. Account prerequisites

Before touching the App dashboard, make sure you have:

### 1.1 A Facebook Page (not a personal profile)
Etnia almost certainly already has one. You need to be an **Admin** on it, not just an Editor.

Verify at: <https://www.facebook.com/pages/?category=your_pages>

### 1.2 An Instagram Business or Creator account
- Open the Instagram app → **Settings & privacy** → **Account type and tools** → **Switch to professional account**.
- Pick **Business** (Creator also works for messaging, but Business is cleaner for an agency).
- During the flow it will ask to connect a Facebook Page — **connect it to the Etnia Page from §1.1**.

If the IG account is already Business but **not** linked to the Page:
- In Instagram: **Settings → Business tools and controls → Connect or create**.
- Or in **Meta Business Suite**: Settings → Business assets → add IG account → link to Page.

This linkage is **mandatory**. Instagram Messaging API only works for Business/Creator accounts linked to a Page.

### 1.3 Meta Business Manager + System User

Go to <https://business.facebook.com> → create a Business account if Etnia doesn't have one → add the Facebook Page as a business asset → add the Instagram account as a business asset.

Then create a **System User**:
- Business Settings → Users → System Users → **Add**.
- Role: **Admin**.
- Name it `etnia-bot-systemuser` (or similar).

System Users are non-human accounts that issue tokens not tied to anyone's personal Facebook login. **Required** if you want the bot to keep working when an employee leaves.

Assign assets to the System User:
- System User detail page → **Add Assets** → Pages → select the Etnia Page → grant **Manage Page**.
- Add Assets → Apps → select your Meta App → grant **Manage App**.

---

## 2. Configure the Meta App

Go to <https://developers.facebook.com/apps> → open your app.

### 2.1 Set the App type
If the app is **Consumer** type, you may need to recreate it as **Business** type — only Business apps can request `instagram_manage_messages` and `pages_messaging`. Check: App Settings → Basic → "App type". If it's Consumer, create a new one as Business and migrate.

### 2.2 Add the Messenger product
- Left sidebar → **Add Product** → **Messenger** → **Set up**.
- Under **Access Tokens** → click **Add or remove Pages** → select the Etnia Page.
- Generate the page access token here for **testing only** — we'll replace it with a System User token in §3.

### 2.3 Add the Instagram product
- Left sidebar → **Add Product** → **Instagram** → **Set up**.
- Pick the **Instagram Messaging** feature (not Basic Display, not Graph API alone).
- Connect the Instagram Business account from §1.2.

### 2.4 Note these values into your `.env`
From **App Settings → Basic**:
```env
META_APP_ID=123456789012345
META_APP_SECRET=abcdef0123...           # Click "Show" — used for HMAC signing
META_PAGE_ID=987654321098765            # From the Page → About → Page ID
META_IG_ACCOUNT_ID=178414...            # From Instagram product page in App dashboard
META_WEBHOOK_VERIFY_TOKEN=pickanyrandomstringhere
```

`META_WEBHOOK_VERIFY_TOKEN` is a secret you invent. Meta will echo it back during webhook subscription to confirm you control the URL.

---

## 3. Generate a long-lived Page Access Token via System User

Short-lived tokens expire in 1–2 hours; the dashboard-generated Page tokens expire in ~60 days. **Use a System User token** — it never expires unless revoked.

In **Business Settings → Users → System Users → [your system user]**:
- Click **Generate New Token**.
- App: select your Meta App.
- Token expiration: **Never**.
- Permissions: tick
  - `pages_messaging`
  - `pages_manage_metadata`
  - `pages_read_engagement`
  - `instagram_basic`
  - `instagram_manage_messages`
  - `business_management`
- Generate → **copy it now**, you cannot see it again.

Save it:
```env
META_PAGE_ACCESS_TOKEN=EAAG...verylong...
```

Verify it works:
```bash
curl "https://graph.facebook.com/v19.0/me?access_token=$META_PAGE_ACCESS_TOKEN"
# → returns the Page object
```

---

## 4. Configure webhooks

### 4.1 Expose your local backend (for development)

You need a public HTTPS URL pointing to your local FastAPI server. Pick one:

- **ngrok** (free): `ngrok http 8000` → gives `https://abcd1234.ngrok-free.app`.
- **Cloudflare Tunnel** (free, persistent): `cloudflared tunnel --url http://localhost:8000`.
- **localtunnel** (free, less reliable): `npx localtunnel --port 8000`.

Once deployed, replace with your real domain.

### 4.2 Add the webhook callback in the App dashboard

In Meta App dashboard → **Webhooks** product (add it if not yet present) → **Edit subscription** for `Page` and `Instagram`.

For both Page and Instagram subscriptions:
- **Callback URL:** `https://your-public-url/webhooks/meta`
- **Verify Token:** the same string you put in `META_WEBHOOK_VERIFY_TOKEN`
- Click **Verify and Save** — Meta sends a `GET` to your URL with `?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<random>`. Your handler must return `hub.challenge` as plain text if the token matches.

Then subscribe to fields:
- **Page:** `messages`, `messaging_postbacks`, `message_reads`, `messaging_optins`
- **Instagram:** `messages`, `messaging_postbacks`, `message_reads`

### 4.3 Subscribe the Page to the App

Webhook subscriptions in the dashboard are at the *App* level. You also need to tell Meta that this specific Page should send events through this App:

```bash
curl -X POST \
  "https://graph.facebook.com/v19.0/$META_PAGE_ID/subscribed_apps" \
  -d "subscribed_fields=messages,messaging_postbacks,message_reads" \
  -d "access_token=$META_PAGE_ACCESS_TOKEN"
# → {"success": true}
```

Verify:
```bash
curl "https://graph.facebook.com/v19.0/$META_PAGE_ID/subscribed_apps?access_token=$META_PAGE_ACCESS_TOKEN"
```

For Instagram, the subscription is implicit once the IG account is connected to the Page and the App is subscribed.

### 4.4 Webhook handler shape (what the bot must implement)

**GET request — verification:**
```
GET /webhooks/meta?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
→ if hub.verify_token == META_WEBHOOK_VERIFY_TOKEN:
     return PlainTextResponse(hub.challenge, status=200)
   else:
     return Response(status=403)
```

**POST request — event delivery:**
```
POST /webhooks/meta
Headers: X-Hub-Signature-256: sha256=<hmac_hex>
Body:    JSON

→ verify HMAC: hmac_sha256(META_APP_SECRET, raw_body) == signature
   if mismatch: return 403
   parse → enqueue Celery job → return 200 within 10s
```

Payload shape (FB Messenger):
```json
{
  "object": "page",
  "entry": [{
    "id": "PAGE_ID",
    "time": 1700000000000,
    "messaging": [{
      "sender": {"id": "USER_PSID"},
      "recipient": {"id": "PAGE_ID"},
      "timestamp": 1700000000000,
      "message": {"mid": "m_...", "text": "Hola, vi su anuncio de Aruba"}
    }]
  }]
}
```

Payload shape (Instagram):
```json
{
  "object": "instagram",
  "entry": [{
    "id": "IG_ACCOUNT_ID",
    "time": 1700000000000,
    "messaging": [{
      "sender": {"id": "IGSID"},
      "recipient": {"id": "IG_ACCOUNT_ID"},
      "timestamp": 1700000000000,
      "message": {"mid": "...", "text": "..."}
    }]
  }]
}
```

Same outer shape — dispatch by `object` field.

---

## 5. Sending messages back

### 5.1 Facebook Messenger
```bash
curl -X POST "https://graph.facebook.com/v19.0/me/messages?access_token=$META_PAGE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": {"id": "USER_PSID"},
    "message": {"text": "Hola! Somos Etnia Viajes."},
    "messaging_type": "RESPONSE"
  }'
```

`messaging_type: "RESPONSE"` is required when replying within the 24-hour window after the user's last message. Outside that window you need `MESSAGE_TAG` with one of the approved tags (rare for this use case — most replies are within minutes).

### 5.2 Instagram
Same endpoint, same Page Access Token. The recipient `id` is the IGSID from the webhook:
```bash
curl -X POST "https://graph.facebook.com/v19.0/me/messages?access_token=$META_PAGE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": {"id": "IGSID"},
    "message": {"text": "Hola! Somos Etnia Viajes."}
  }'
```

IG has a stricter 24-hour window with no tag exceptions for promotional content. Stick to responses.

### 5.3 Sending media
```json
{
  "recipient": {"id": "..."},
  "message": {
    "attachment": {
      "type": "image",
      "payload": {"url": "https://...", "is_reusable": true}
    }
  }
}
```

Media must be on a public HTTPS URL accessible to Meta's servers.

---

## 6. Testing in Development Mode

Until App Review approves your permissions, the App is in **Development Mode** — only people with a role on the App can interact with it.

### 6.1 Add testers
App dashboard → **Roles** → **Roles** → add yourself + dev team as **Admin** or **Tester**. They must accept the invite from notifications on facebook.com.

### 6.2 End-to-end smoke test
1. Tester sends a DM to the Etnia Facebook Page or Instagram account from their personal profile.
2. Webhook fires → tail your local logs to confirm it arrived.
3. Bot responds via the Send API → message appears back in Messenger / Instagram.

If step 2 doesn't fire:
- Check **App Dashboard → Webhooks → Recent deliveries**. Failed deliveries show the response body Meta saw — usually 403 (HMAC mismatch) or 5xx (your handler crashed).
- Check the Page is subscribed: `GET /{PAGE_ID}/subscribed_apps`.
- Check your tunnel is still up.

### 6.3 Common errors

| Error | Cause | Fix |
|---|---|---|
| `(#10) Application does not have permission` | Missing `pages_messaging` or trying to message someone who hasn't messaged you first | Get the user to message you first; Meta's "page messages users, not the other way around" rule |
| `(#100) No matching user` | Wrong PSID/IGSID, or testing across different App IDs (PSIDs are App-scoped) | Use the PSID exactly as received in the webhook |
| Webhook 403 | HMAC mismatch — usually because you JSON-encoded the body before HMAC instead of using the raw bytes | Compute HMAC on `await request.body()`, not on `json.dumps(...)` |
| `(#200) The user has not authorized application` | App in dev mode and target is not a tester | Add them as a tester, or wait for App Review |

---

## 7. App Review (production)

Once dev-mode testing works end-to-end, submit for review.

App Dashboard → **App Review** → **Permissions and Features** → for each permission listed in §3, click **Request advanced access**.

For each permission Meta wants:
1. **Use case description** — 1–2 paragraphs of why you need it.
2. **Screencast** — record a 1-minute screen recording showing a real flow that uses the permission. (Loom or QuickTime is fine.)
3. **Test credentials** — give Meta a test account they can use to reproduce.
4. **Privacy Policy URL** — public URL, must mention what data you collect.
5. **Data Deletion URL** — endpoint or instructions for users to request deletion.

Realistic timeline: **5–15 business days**. First submission often gets rejected for vague descriptions or unclear screencasts. Iterate. Don't submit on a Friday.

Meanwhile, the App keeps working in dev mode — you can soft-launch with a small user group by adding them as testers.

### 7.1 Business Verification
Meta also requires **Business Verification** for advanced messaging permissions. This is a one-time process where you upload Etnia's official documents (CUIT registration, utility bill at the registered address, etc.). Start it early — it can take a week independent of App Review.

---

## 8. Going to production checklist

- [ ] App Review approved for all required permissions.
- [ ] Business Verification complete.
- [ ] Webhook URL points to production domain (not ngrok).
- [ ] HMAC verification enabled and tested with intentional bad signatures.
- [ ] System User token stored in production secrets manager (not in `.env` on the server).
- [ ] App switched from **Development** to **Live** mode.
- [ ] Page subscribed to webhooks confirmed via `GET /{PAGE_ID}/subscribed_apps`.
- [ ] Logging in place for every inbound and outbound message (with PII redaction policy decided).
- [ ] Rate limiting on `/webhooks/meta` (e.g. 100 req/sec per IP) to prevent abuse if URL leaks.
- [ ] Monitoring/alert if webhook deliveries start failing (Meta dashboard shows delivery rate).

---

## Reference links

- Messenger Platform overview: <https://developers.facebook.com/docs/messenger-platform>
- Instagram Messaging API: <https://developers.facebook.com/docs/messenger-platform/instagram>
- Webhooks reference: <https://developers.facebook.com/docs/graph-api/webhooks>
- App Review process: <https://developers.facebook.com/docs/app-review>
- Graph API Explorer (great for testing token calls): <https://developers.facebook.com/tools/explorer/>
