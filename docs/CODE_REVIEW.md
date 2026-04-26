# Etnia CRM — Code Review & Architecture Plan

> **Status:** Plan document, pre-implementation. No Phase B+ code has been written yet. Phase A hot-fixes (§3) have already shipped.
> **Last updated:** 2026-04-25 (decisions section refreshed).
> **Diagrams:** Mermaid. Renders in GitHub, VS Code (with a Mermaid extension), and most modern Markdown viewers.

---

## Table of contents

0. [Executive summary](#0-executive-summary)
1. [Goals & non-goals](#1-goals--non-goals)
2. [Current state audit (post hot-fixes)](#2-current-state-audit-post-hot-fixes)
3. [Hot-fixes already shipped (Phase A)](#3-hot-fixes-already-shipped-phase-a)
4. [Inconsistencies introduced by the hot-fixes](#4-inconsistencies-introduced-by-the-hot-fixes)
5. [Open issues not yet addressed](#5-open-issues-not-yet-addressed)
6. [Target architecture](#6-target-architecture)
7. [Data model (Postgres)](#7-data-model-postgres)
8. [Conversation state machine](#8-conversation-state-machine)
9. [Target file & module layout](#9-target-file--module-layout)
10. [API surface](#10-api-surface)
11. [Environment variables](#11-environment-variables)
12. [Implementation plan (phases B–F)](#12-implementation-plan-phases-bf)
13. [Testing strategy](#13-testing-strategy)
14. [Data migration from Sheets](#14-data-migration-from-sheets)
15. [Risks & mitigations](#15-risks--mitigations)
16. [Open decisions (needed before Phase B)](#16-open-decisions-needed-before-phase-b)

---

## 0. Executive summary

**What we have today:** a WhatsApp-only FastAPI bot that qualifies travel leads via OpenAI, persists ephemeral session state in Redis, and syncs snapshots to a Google Sheet as a pseudo-database. Handoff is a dead-end state that returns `400`. There is no multi-channel support, no real CRM persistence, and no agent workflow.

**What we are building:** a multi-channel CRM for Etnia Viajes that ingests WhatsApp, Instagram DMs, and Facebook Messenger messages through **Chatwoot** as the operational inbox, uses the existing bot logic for lead qualification, and stores structured CRM data (contacts, conversations, qualification, deals) in **Postgres on Supabase**. Agents work inside Chatwoot; our FastAPI service orchestrates the bot, enriches conversations with qualification data, and exposes an analytics surface backed by Postgres.

**Key architectural decisions (made in prior conversation):**

| Decision                  | Choice                                                                                     | Alternative rejected                                |
| ------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| Multi-channel abstraction | **Chatwoot** (self-hosted on Hetzner, ~US$5/mo) handles WA/IG/FB inboxes                   | Build a custom Next.js inbox (4–8 weeks of UI work) |
| Persistent database       | **Postgres on Supabase** (free tier)                                                       | Neon; Sheets-as-DB                                  |
| Hosting for Chatwoot      | Hetzner CX22 (€4.5/mo)                                                                     | DigitalOcean, Vultr, Chatwoot Cloud                 |
| Session/bot cache         | **Drop Redis entirely**, move bot state into Postgres                                      | Keep Redis (Upstash)                                |
| Async workers             | **Drop Celery entirely** for now                                                           | Keep Celery + Redis broker                          |
| Google Sheets role        | One-time migration import, then retired                                                    | Keep as hourly export                               |
| Multi-tenancy             | Single tenant (Etnia only), clean boundaries so a future 2nd tenant is a 1-week refactor   | Full multi-tenant schema from day 1                 |
| Agent UI                  | **Chatwoot** for operational inbox; custom tiny Next.js dashboard only for analytics/deals | Build full custom agent UI                          |
| Webpage catalog           | **Separate Supabase project** owned by web team (`destinations`, `multidestination_packages`); CRM reads via REST API, no cross-project FK | Single Supabase shared by webpage + CRM             |

**Revised scope vs the original plan:**

- **Dropping Redis and Celery simplifies the stack dramatically.** With Chatwoot owning channel adapters and Postgres as the single source of truth, we eliminate two full infrastructure components. The current `tasks.py` + `celery_app.py` + `redis_services.py` go away.
- **No "channel adapters" of our own.** Chatwoot abstracts WhatsApp/IG/FB. Our bot only speaks two protocols: receive from Chatwoot's webhook, reply via Chatwoot's REST API.

**What this document gives you:** a file-by-file, table-by-table, phase-by-phase plan you can review and approve before we write any more code.

---

## 1. Goals & non-goals

### Goals

1. One inbox for WhatsApp + Instagram + Facebook, handled by Etnia's sales agents.
2. Bot qualifies the lead before the human takes over (current logic preserved, not redesigned).
3. All contacts, conversations, qualifications, and deals queryable in Postgres.
4. Handoff produces a **usable notification + context** for the agent, not a dead `400`.
5. Code structured so the WhatsApp-specific assumptions are removed from business logic.
6. Deployable to production on a ~$10/mo budget (Hetzner VPS + Supabase free tier + bot-api host).

### Non-goals (Phase 1)

- Multi-tenant SaaS. Clean boundaries only.
- Custom full-featured agent UI. Chatwoot fills that role.
- Real-time analytics dashboards. Basic Postgres queries + Supabase studio are enough for v1.
- Automated deal progression beyond "qualified → handed off".
- Migration of the full Redis session history — only the Sheets summary survives.

---

## 2. Current state audit (post hot-fixes)

### 2.1 Runtime topology (today)

```mermaid
flowchart LR
    U[User on WhatsApp] -->|message| WPP[WPP Adapter<br/>unofficial WPPConnect]
    WPP -->|POST /webhook/| API[FastAPI<br/>uvicorn]
    API -->|session state| R[(Redis<br/>self-hosted)]
    API -->|LLM call| OAI[OpenAI<br/>gpt-4o-mini]
    API -->|reply| WPP
    API -->|enqueue| C[Celery worker]
    C -->|read sessions| R
    C -->|write rows| GS[(Google Sheets)]
    API -.->|ads / offers| JSON[JSON files<br/>on disk]
```

**Single-channel. Single-writer. Sheets is the "database". Redis holds the only persistent conversation state.**

### 2.2 Strengths (keep these)

- Clear state machine in `app/core/enums.py` (`SessionState`). Keep the enum; extend it.
- Bot pipeline is nicely split: guard → classifier/extractor → reply. Keep `PreClasifyerService` and `LLMExtractionService` largely as-is.
- FastAPI dependency-injection is used consistently. Good foundation to extend.
- Offer presentation is deterministic (no LLM for the greeting or the pre-built offer text). Keep that.

### 2.3 Weaknesses (remediated or to remediate)

See §3 (already fixed), §4 (inconsistencies to fix), §5 (not yet addressed).

---

## 3. Hot-fixes already shipped (Phase A)

These were landed in the current branch. No behaviour decisions; all are correctness fixes.

| #   | File                              | Fix                                                                                                    |
| --- | --------------------------------- | ------------------------------------------------------------------------------------------------------ |
| A1  | `app/services/chatbot_service.py` | Dispatcher no longer returns `None` for unhandled state — hands off and returns `200 ok`.              |
| A2  | `app/services/chatbot_service.py` | `count_requests` persists on guard rejection, timeout, max-requests, and unhandled state.              |
| A3  | `app/services/chatbot_service.py` | `date_of_contact` parse failure is caught, logged, and reset to now (instead of uncaught 500).         |
| A4  | `app/services/chatbot_service.py` | Timeout returns `200 ok` (handed off) instead of `400`.                                                |
| A5  | `app/services/session_service.py` | Redis connectivity errors propagate instead of silently treating the user as new.                      |
| A6  | `app/services/session_service.py` | Sessions now expire after 7 days (`SESSION_TTL_SECONDS`).                                              |
| A7  | `app/services/session_service.py` | Request body parsed once via `WebhookPayloadDep`, cached on `request.state`.                           |
| A8  | `app/utils/message_manager.py`    | Deleted dead `word_to_num` / `get_month_from_message`.                                                 |
| A9  | `app/utils/message_manager.py`    | `get_offer_summary_for_destination_key` no longer crashes on unknown key.                              |
| A10 | `app/utils/whatsapp.py`           | `raise_for_status()` on every send; structured logging of failures.                                    |
| A11 | `app/services/sheets_services.py` | Removed the unintended `value_on_sheet.lower() == value_on_sheet` guard that silently blocked updates. |

---

## 4. Inconsistencies introduced by the hot-fixes

> You were right to flag this. Two changes were correct as bug-fixes but leave internal state inconsistent with the target architecture. Calling them out so they are explicitly addressed in Phase B, not quietly carried along.

### 4.1 Session keying still encodes WhatsApp

`app/services/session_service.py:18` keeps `SESSION_PREFIX = "wa_session:"` and `get_session_key` returns `SESSION_PREFIX + self.from_number`. The `get_session` dependency at line 77 reads `payload.get("From")` — a WhatsApp-shaped field name.

**Why this is wrong going forward:**

- Phase B removes Redis entirely; the whole `RedisSession` class disappears. Keeping the `wa_session:` prefix is a short-term lie.
- The `from_number` parameter name is WhatsApp-specific. In the target model this becomes an `external_user_id` that is a phone number for WA, an IGSID for Instagram, a PSID for FB Messenger.
- The `From` field is a WPPConnect adapter convention. Chatwoot sends a different shape.

**Resolution:** left as-is for Phase A (don't churn the code when it's about to be removed). Phase B drops the whole `session_service.py` module in favour of Postgres-backed state indexed by `(channel, external_user_id)` pulled from the Chatwoot webhook.

### 4.2 `ChatbotService.process_message` still takes WhatsApp-shaped args

Signature: `process_message(redis_session, from_number, body, name)`. Internally it calls `send_whatsapp_text(from_number, ...)` in multiple places.

**Resolution:** Phase B changes the signature to `process_message(incoming: IncomingMessage, sender: MessageSender)`. `IncomingMessage` carries `channel`, `external_user_id`, `conversation_id` (from Chatwoot), `text`, `sender_name`, `received_at`. `MessageSender` is a Protocol implemented by `ChatwootSender`.

### 4.3 `sync_sheets_with_redis_task.delay()` still called on every message

Hot-fixes left Celery + Sheets sync in place (they still work and do no harm). They go away in Phase C when Postgres takes over.

---

## 5. Open issues not yet addressed

Listed from §2 of the original review, annotated with whether they are resolved by the Phase B–F plan or need a targeted fix.

| #   | Issue                                                                                                                                                  | Resolution path                                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| O1  | IATA city matching uses substring + fuzzy with duplicate variants across codes (`"mar del plata"` in both MDP & MDQ). Non-deterministic on dict order. | **Phase F task:** rebuild `CITIES` as a single list of `(iata, canonical_name, aliases, region)` tuples; match by normalized canonical first, alias second, fuzzy as last resort. Add unit tests with ≥50 real examples. |
| O2  | `normalize_text` strips accent characters but does not _fold_ them. `"córdoba"` and `"cordoba"` are different inputs.                                  | Fix alongside O1. Use `unicodedata.normalize("NFKD", s)` + strip combining marks.                                                                                                                                        |
| O3  | `llm_extraction_service._compute_completeness` reads a `required_fields` session key that is never set.                                                | **Phase D task:** either plumb `required_fields` through (per destination) or delete the branch.                                                                                                                         |
| O4  | System message in `messages[]` comes after the history in `llm_extraction_service.extract`.                                                            | Trivial reorder during Phase D refactor.                                                                                                                                                                                 |
| O5  | `TotalStates` enum overlaps with `SessionState`. Relies on member names matching values.                                                               | **Phase B:** collapse into `SessionState` with a `.label` property.                                                                                                                                                      |
| O6  | `sheets_services._create_update_request` breaks past column Z (`chr(66 + i)`).                                                                         | **Phase C:** Sheets module deleted. N/A.                                                                                                                                                                                 |
| O7  | `tasks.py` sort crashes on empty data / missing `FECHA` column.                                                                                        | Phase C: Celery+Sheets removed. N/A.                                                                                                                                                                                     |
| O8  | `pre_clasifyer_service` fail-closed on OpenAI errors → user dropped silently.                                                                          | **Phase D behaviour decision needed** (see §16).                                                                                                                                                                         |
| O9  | Typos: `pre_clasifyer_service`, `wpp_clinet_lifespan`.                                                                                                 | Phase B rename during restructure.                                                                                                                                                                                       |
| O10 | `app/services/__init.py` (missing underscore) — not imported anywhere so silently a no-op.                                                             | Phase B cleanup.                                                                                                                                                                                                         |
| O11 | `Config` classes in `app/config.py` instantiate at import time. Missing env var → import error everywhere.                                             | **Phase B:** wrap each in `@lru_cache` getter.                                                                                                                                                                           |
| O12 | No webhook signature verification (Chatwoot bot token header at minimum).                                                                              | **Phase C required:** HMAC/bearer check on `/webhooks/chatwoot`.                                                                                                                                                         |
| O13 | No rate limiting.                                                                                                                                      | **Phase F:** add `slowapi` on `/webhooks/chatwoot`.                                                                                                                                                                      |
| O14 | Logs include message bodies, no PII redaction.                                                                                                         | **Phase F:** add structured logging with a redactor for text ≥ X chars.                                                                                                                                                  |
| O15 | `celery_writer.ipynb` and `reproduce_issue.py` loose at repo root.                                                                                     | Phase B cleanup: `ipynb` → delete or move to `notebooks/`, script → `scripts/`.                                                                                                                                          |
| O16 | Only 2 legacy tests; dispatcher untested.                                                                                                              | Phase B: add `pytest` + `pytest-asyncio` scaffolding, cover new domain layer.                                                                                                                                            |

---

## 6. Target architecture

### 6.1 System context (what the outside world sees)

```mermaid
flowchart LR
    subgraph USERS[Customers]
        WA[WhatsApp user]
        IG[Instagram user]
        FB[Facebook user]
    end

    subgraph META[Meta Platform]
        WAAPI[WhatsApp Cloud API]
        IGAPI[Instagram Graph API]
        FBAPI[Messenger Platform]
    end

    subgraph ETNIA[Etnia infra]
        CW[Chatwoot<br/>Hetzner VPS]
        BOT[Etnia Bot API<br/>FastAPI]
        PG[(Postgres<br/>Supabase)]
    end

    subgraph AGENTS[Sales team]
        A1[Agent 1]
        A2[Agent 2]
    end

    WA <--> WAAPI
    IG <--> IGAPI
    FB <--> FBAPI
    WAAPI <--> CW
    IGAPI <--> CW
    FBAPI <--> CW
    CW -- webhook --> BOT
    BOT -- reply via REST --> CW
    BOT <--> PG
    A1 <--> CW
    A2 <--> CW
    BOT -.-> OAI[OpenAI]
```

Only two integration surfaces for our code:

- **Inbound:** Chatwoot `message_created` webhook → `POST /webhooks/chatwoot`.
- **Outbound:** Chatwoot REST API for replies, labels, assignments, private notes.

### 6.2 Container view (what runs where)

```mermaid
flowchart TB
    subgraph HETZNER["Hetzner VPS — 4 GB RAM, ~US$5/mo"]
        direction TB
        CADDY[Caddy<br/>TLS + reverse proxy]
        CWAPP[Chatwoot Rails<br/>:3000]
        CWDB[(Chatwoot Postgres)]
        CWREDIS[(Chatwoot Redis)]
        CWSIDEKIQ[Chatwoot Sidekiq]
        CADDY --> CWAPP
        CWAPP --> CWDB
        CWAPP --> CWREDIS
        CWSIDEKIQ --> CWDB
        CWSIDEKIQ --> CWREDIS
    end

    subgraph BOTHOST["Bot API host (Fly.io / Render / same VPS)"]
        direction TB
        UV[Uvicorn + FastAPI<br/>app.app]
    end

    subgraph SUPABASE["Supabase — CRM project (free tier)"]
        direction TB
        ETNIAPG[(Etnia Postgres<br/>500 MB)]
        SBAUTH[Auth<br/>optional]
        SBSTORAGE[Storage<br/>optional]
    end

    subgraph WEBSB["Supabase — Webpage project (separate, owned by web team)"]
        direction TB
        WEBPG[(destinations<br/>multidestination_packages)]
    end

    CWAPP <-- webhook + REST --> UV
    UV <-- asyncpg --> ETNIAPG
    UV -. read-only REST .-> WEBPG
    UV -. OpenAI API .-> OAI[OpenAI<br/>gpt-4o-mini]
```

### 6.3 Request flow — incoming message

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Meta
    participant Chatwoot
    participant BotAPI as Bot API<br/>/webhooks/chatwoot
    participant PG as Etnia Postgres
    participant OAI as OpenAI

    User->>Meta: "Hola, vi el anuncio de Aruba"
    Meta->>Chatwoot: channel webhook event
    Chatwoot->>Chatwoot: persist Contact + Conversation + Message
    Chatwoot->>BotAPI: POST message_created
    BotAPI->>BotAPI: verify api_access_token header
    BotAPI->>PG: upsert Contact / ExternalAccount / Conversation
    BotAPI->>PG: load (or create) BotState
    BotAPI->>OAI: PreClassifier + LLMExtractor
    OAI-->>BotAPI: classification + extraction
    BotAPI->>PG: update BotState, insert QualificationEvent
    BotAPI->>Chatwoot: POST /conversations/{id}/messages (reply)
    Chatwoot->>Meta: forward reply
    Meta->>User: "¡Hola! Somos Etnia Viajes…"
    BotAPI-->>Chatwoot: 200 OK
```

### 6.4 Request flow — handoff to human

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Chatwoot
    participant BotAPI as Bot API
    participant PG as Etnia Postgres
    participant Agent

    User->>Chatwoot: "Sí, me interesa esa oferta"
    Chatwoot->>BotAPI: message_created webhook
    BotAPI->>BotAPI: LLM detects offer_accepted = true
    BotAPI->>Chatwoot: POST reply "¡Perfecto! Un asesor…"
    BotAPI->>Chatwoot: POST private note (qualification summary)
    BotAPI->>Chatwoot: POST label "handoff-with-offer"
    BotAPI->>Chatwoot: POST toggle_status / assignment
    BotAPI->>PG: conversation.status='handed_off'
    BotAPI->>PG: insert qualification_event(type='handoff')
    BotAPI->>PG: insert deal(stage='lead')
    Note over Chatwoot,Agent: Chatwoot notifies team
    Agent->>Chatwoot: claims + replies
    Chatwoot->>User: agent's reply via channel
    Note over BotAPI: further messages on this<br/>conversation are ignored
```

Crucially: once a human is assigned, the bot **does not** reply to subsequent messages on that conversation. Enforced by checking `conversation.status` in Postgres (or the Chatwoot assignment state) in the webhook handler.

---

## 7. Data model (Postgres)

### 7.1 ERD

```mermaid
erDiagram
    contacts ||--o{ external_accounts : has
    contacts ||--o{ conversations : has
    contacts ||--o{ deals : has
    conversations ||--o{ qualification_events : generates
    conversations ||--o| bot_states : tracks
    conversations ||--o{ deals : may_create
    agents ||--o{ conversations : assigned_to

    contacts {
        uuid id PK
        text full_name
        text phone
        int chatwoot_contact_id "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    external_accounts {
        uuid id PK
        uuid contact_id FK
        channel channel "enum wa_ig_fb"
        text external_id "phone_IGSID_PSID"
        timestamptz created_at
    }

    conversations {
        uuid id PK
        uuid contact_id FK
        channel channel
        int chatwoot_conversation_id "nullable,unique"
        conversation_status status
        session_state bot_state
        int num_adults
        int num_children
        text destination
        text departure_city
        text departure_date
        timestamptz last_inbound_at
        int assigned_agent_id FK "chatwoot id"
    }

    bot_states {
        uuid conversation_id PK "FK to conversations"
        int count_requests
        jsonb messages_history
        timestamptz date_of_contact
        timestamptz updated_at
    }

    qualification_events {
        bigserial id PK
        uuid conversation_id FK
        text event_type "guard_llm_state_handoff"
        jsonb payload
        timestamptz created_at
    }

    deals {
        uuid id PK
        uuid contact_id FK
        uuid conversation_id FK "nullable"
        deal_stage stage "lead_quoted_booked_paid_lost"
        numeric amount_usd
        text notes
        timestamptz created_at
        timestamptz updated_at
    }

    offers {
        uuid id PK
        uuid destination_id "external; webpage Supabase"
        uuid package_id "external; webpage Supabase"
        text key UK "stable matching key"
        text aliases "text[]"
        text title
        text summary_text
        text destination_name "denormalized snapshot"
        int price_from
        varchar currency
        date valid_from
        date valid_until
        bool is_active
        jsonb payload
        timestamptz created_at
        timestamptz updated_at
    }

    agents {
        int chatwoot_agent_id PK
        text name
        text email
        text role
    }

    tenant_config {
        int id PK "always 1"
        text chatwoot_base_url
        text chatwoot_account_id
        jsonb channel_map "inbox_id->channel"
        timestamptz updated_at
    }
```

**Constraints that Mermaid erDiagram cannot express** (enforced in the DDL below):

- `external_accounts` — `UNIQUE (channel, external_id)`.
- `conversations.chatwoot_conversation_id` — `UNIQUE`, nullable.
- `bot_states.conversation_id` — both `PK` and `FK` to `conversations.id`, `ON DELETE CASCADE`.
- `tenant_config.id` — `CHECK (id = 1)` (single-row table). The name is a misnomer kept for historical reasons — this table holds **Chatwoot connection settings** (base URL, account id, inbox→channel map), not multi-tenant boundaries. Considered renaming to `chatwoot_config` (cosmetic, deferred).
- `contacts.chatwoot_contact_id` — `UNIQUE`, nullable.
- `offers.key` — `UNIQUE`. `valid_until >= valid_from` when both set.
- `offers.destination_id` and `offers.package_id` — reference rows in a **separate Supabase project** (the webpage catalog); not enforced as FKs. Validated at the app layer on insert/update; reconciled nightly.
- `qualification_events` is an **append-only audit log** of bot activity (guard rejections, LLM extractions, state transitions, handoffs), not the travel-data store. The qualification fields themselves live denormalized on `conversations` + the `qualification` jsonb. The events table is optional in v1 if audit isn't a priority.

### 7.2 Concrete DDL (Alembic migration `0001_initial.sql` preview)

```sql
-- enums
CREATE TYPE channel AS ENUM ('whatsapp', 'instagram', 'facebook');
CREATE TYPE conversation_status AS ENUM ('bot', 'handed_off', 'closed');
CREATE TYPE session_state AS ENUM (
    'presenting_offers',
    'extracting_information',
    'handoff_with_offer',
    'handoff_no_offer',
    'handoff_timeout',
    'handoff_unknown_destination'
);
CREATE TYPE deal_stage AS ENUM ('lead', 'quoted', 'booked', 'paid', 'lost');

-- tenant_config (single-row)
CREATE TABLE tenant_config (
    id smallint PRIMARY KEY CHECK (id = 1),
    chatwoot_base_url text NOT NULL,
    chatwoot_account_id text NOT NULL,
    channel_map jsonb NOT NULL DEFAULT '{}',
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- contacts
CREATE TABLE contacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name text,
    email text,
    phone text,
    chatwoot_contact_id int UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX contacts_phone_idx ON contacts (phone) WHERE phone IS NOT NULL;

-- external_accounts
CREATE TABLE external_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel channel NOT NULL,
    external_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (channel, external_id)
);

-- conversations
CREATE TABLE conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id uuid NOT NULL REFERENCES contacts(id),
    channel channel NOT NULL,
    chatwoot_conversation_id int UNIQUE,
    status conversation_status NOT NULL DEFAULT 'bot',
    bot_state session_state NOT NULL DEFAULT 'presenting_offers',
    destination text,
    offer_type text,
    destination_key text,
    qualification jsonb NOT NULL DEFAULT '{}',
    last_inbound_at timestamptz,
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    assigned_agent_id int
);
CREATE INDEX conversations_contact_idx ON conversations (contact_id);
CREATE INDEX conversations_status_idx ON conversations (status);

-- bot_states (1:1 with conversation while bot active; deleted on handoff optional)
CREATE TABLE bot_states (
    conversation_id uuid PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    count_requests int NOT NULL DEFAULT 0,
    messages_history jsonb NOT NULL DEFAULT '[]',
    date_of_contact timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- qualification_events (append-only audit log)
CREATE TABLE qualification_events (
    id bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qe_conv_idx ON qualification_events (conversation_id);
CREATE INDEX qe_type_idx ON qualification_events (event_type);

-- deals
CREATE TABLE deals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id uuid NOT NULL REFERENCES contacts(id),
    conversation_id uuid REFERENCES conversations(id),
    stage deal_stage NOT NULL DEFAULT 'lead',
    amount_usd numeric(12,2),
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- agents (mirror of Chatwoot agents for local lookups)
CREATE TABLE agents (
    chatwoot_agent_id int PRIMARY KEY,
    name text NOT NULL,
    email text,
    role text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- offers (bot-facing monthly catalog; replaces the JSON files on disk).
-- destination_id / package_id reference rows in a SEPARATE Supabase project
-- (the webpage's catalog), so no FK constraint is possible. Validated at the
-- app layer on insert/update; refreshed by a nightly reconciliation job that
-- also flags rows whose external id no longer resolves.
CREATE TABLE offers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    destination_id uuid,                                 -- external; webpage Supabase
    package_id uuid,                                     -- external; webpage Supabase
    key text NOT NULL UNIQUE,                            -- stable bot-matching key
    aliases text[] NOT NULL DEFAULT '{}',                -- normalized lookup aliases
    title text NOT NULL,
    summary_text text NOT NULL,                          -- deterministic text the bot sends
    destination_name text,                               -- denormalized snapshot
    destination_slug text,
    country text,
    price_from int,
    currency varchar(3),
    valid_from date,
    valid_until date,
    is_active boolean NOT NULL DEFAULT true,
    payload jsonb NOT NULL DEFAULT '{}',                 -- legs, inclusions, image url, etc.
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT offers_valid_window CHECK
        (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);
CREATE INDEX offers_active_idx       ON offers (is_active) WHERE is_active;
CREATE INDEX offers_destination_idx  ON offers (destination_id);
CREATE INDEX offers_package_idx      ON offers (package_id);
CREATE INDEX offers_key_lower_idx    ON offers (lower(key));
CREATE INDEX offers_aliases_gin_idx  ON offers USING gin (aliases);

-- shared trigger reused by other tables that need updated_at maintenance
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;

CREATE TRIGGER offers_set_updated_at
BEFORE UPDATE ON offers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### 7.3 What lives where

| Data                                                 | System of record                         | Duplicated?                                                                   |
| ---------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------- |
| Contact identity (name/email/phone)                  | Chatwoot                                 | Yes, mirrored in our `contacts` with `chatwoot_contact_id` link               |
| Conversation messages (full text)                    | Chatwoot                                 | **No** — we don't mirror message bodies. Fetch from Chatwoot API when needed. |
| Bot's rolling `messages_history` for LLM             | Postgres (`bot_states`)                  | No — our own slice, truncated to N most recent turns                          |
| Qualification fields (destination, travelers, date…) | Postgres (`conversations.qualification`) | No                                                                            |
| Offer catalog (bot-facing)                           | Postgres `offers` (CRM project)          | No — replaces today's `offers.json` after Phase E                              |
| Webpage catalog (`destinations`, `multidestination_packages`) | **Separate Supabase project** (web team) | Selected fields denormalized into `offers` for offline reads                  |
| Ad/funnel config (Meta ad → destination_key map)     | JSON files on disk                       | No — small enough to stay in version control                                   |
| Agent assignments                                    | Chatwoot                                 | Denormalized for read-speed in `conversations.assigned_agent_id`              |
| Deal pipeline                                        | Postgres (`deals`)                       | No                                                                            |

---

## 8. Conversation state machine

Collapsing `SessionState` + `TotalStates` into a single enum. Added `BOT_ENDED_OK` (optional) for fully completed flows that didn't need a human.

```mermaid
stateDiagram-v2
    [*] --> PRESENTING_OFFERS: first message matches a known ad
    [*] --> HANDOFF_UNKNOWN_DESTINATION: first message doesn't match any ad

    PRESENTING_OFFERS --> HANDOFF_WITH_OFFER: user accepts pre-built offer
    PRESENTING_OFFERS --> EXTRACTING_INFORMATION: user wants custom quote<br/>(missing fields)
    PRESENTING_OFFERS --> HANDOFF_NO_OFFER: user gave complete custom info
    PRESENTING_OFFERS --> HANDOFF_TIMEOUT: >1h since contact
    PRESENTING_OFFERS --> HANDOFF_TIMEOUT: >10 turns

    EXTRACTING_INFORMATION --> EXTRACTING_INFORMATION: still missing fields
    EXTRACTING_INFORMATION --> HANDOFF_NO_OFFER: all fields collected
    EXTRACTING_INFORMATION --> HANDOFF_TIMEOUT: >1h since contact
    EXTRACTING_INFORMATION --> HANDOFF_TIMEOUT: >10 turns

    HANDOFF_WITH_OFFER --> [*]
    HANDOFF_NO_OFFER --> [*]
    HANDOFF_TIMEOUT --> [*]
    HANDOFF_UNKNOWN_DESTINATION --> [*]
```

**Handoff semantics (new):** entering any `HANDOFF_*` state triggers three Chatwoot API calls:

1. `POST /messages` with `private: true` containing the qualification summary (label, destination, travelers, date, departure).
2. `POST /labels` applying a label matching the state name (lowercased with dashes).
3. `POST /toggle_status` or `POST /assignments` to disconnect the bot from the conversation.

After these, the bot ignores subsequent `message_created` events for that conversation unless an agent re-attaches the bot via a label convention (e.g. tagging `bot-takeover`).

---

## 9. Target file & module layout

```
difusionwsp/
├── alembic/                        # NEW — DB migrations
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── app/
│   ├── __init__.py
│   ├── app.py                      # FastAPI entry + lifespan
│   ├── config.py                   # MODIFIED — lru_cache getters
│   ├── api/
│   │   ├── __init__.py
│   │   ├── tag.py
│   │   ├── dependencies.py         # MODIFIED — no more sheets dep
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── chatwoot_webhook.py # NEW — replaces webhook_router.py
│   │       └── health.py           # NEW
│   ├── core/
│   │   ├── __init__.py
│   │   ├── enums.py                # MODIFIED — single SessionState w/ label
│   │   └── exceptions.py
│   ├── domain/                     # NEW — DB-backed entities & repos
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── schemas.py              # Pydantic DTOs (IncomingMessage etc)
│   │   └── repositories.py
│   ├── db/                         # NEW — replaces app/database/
│   │   ├── __init__.py
│   │   └── session.py              # asyncpg/SQLAlchemy async engine
│   ├── integrations/               # NEW
│   │   ├── __init__.py
│   │   ├── chatwoot.py             # ChatwootClient: send, note, label, toggle
│   │   └── web_catalog.py          # WebCatalogClient: read-only REST to webpage Supabase
│   ├── services/
│   │   ├── __init__.py             # FIX rename from __init.py
│   │   ├── chatbot_service.py      # MODIFIED — consumes IncomingMessage
│   │   ├── llm_extraction_service.py  # MODIFIED — no required_fields dead branch
│   │   ├── pre_classifier_service.py  # RENAMED (was pre_clasifyer_service)
│   │   └── agents/
│   │       └── system_prompts.py
│   └── utils/
│       ├── __init__.py
│       ├── message_manager.py      # MODIFIED — IATA rebuild (Phase F)
│       └── text.py                 # NEW — normalize_text w/ accent folding
├── docs/
│   ├── CODE_REVIEW.md              # THIS FILE
│   ├── CHATWOOT_SETUP.md
│   └── META_SETUP.md
├── scripts/                        # NEW — one-shots
│   ├── migrate_from_sheets.py
│   ├── backfill_contacts.py
│   ├── migrate_offers_from_json.py # JSON offers → Postgres offers table
│   └── reconcile_offers.py         # nightly: refresh denorm + flag stale external ids
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── notebooks/                      # NEW — for celery_writer.ipynb etc
├── Dockerfile                      # MODIFIED — uvicorn entrypoint
├── docker-compose.yml              # NEW — api + postgres (dev only)
├── requirements.txt
├── alembic.ini                     # NEW
├── pyproject.toml                  # NEW — consolidated tooling config
└── .env.example                    # NEW — documents required env
```

**Deleted in Phase C:**

- `app/celery_app.py`
- `app/tasks.py`
- `app/services/redis_services.py`
- `app/services/sheets_services.py`
- `app/services/session_service.py` (fully absorbed by `domain/repositories.py`)
- `app/database/redis.py`
- `app/database/sheets.py`
- `app/api/routers/sheets_router.py`
- `app/api/master_router.py`
- `app/utils/whatsapp.py` (replaced by `integrations/chatwoot.py`)
- `reproduce_issue.py` (move to `scripts/` or delete)

---

## 10. API surface

### 10.1 Webhooks (inbound)

| Method | Path                 | Purpose                                                             | Auth                                        |
| ------ | -------------------- | ------------------------------------------------------------------- | ------------------------------------------- |
| `POST` | `/webhooks/chatwoot` | Receive Chatwoot events (`message_created`, `conversation_updated`) | `api_access_token` header = Agent Bot token |

### 10.2 Internal API (for future custom dashboard, optional)

| Method  | Path                               | Purpose                             |
| ------- | ---------------------------------- | ----------------------------------- |
| `GET`   | `/conversations?status=handed_off` | List handed-off conversations       |
| `GET`   | `/conversations/{id}`              | Conversation detail + qualification |
| `GET`   | `/deals?stage=lead`                | Deal pipeline                       |
| `PATCH` | `/deals/{id}`                      | Update deal stage/amount/notes      |

All under `/api/v1/` with Supabase Auth (`Authorization: Bearer <jwt>`) if we build the dashboard. Deferred past Phase F.

### 10.3 Health

| Method | Path       | Purpose                                          |
| ------ | ---------- | ------------------------------------------------ |
| `GET`  | `/healthz` | Liveness (returns `{"ok": true}`)                |
| `GET`  | `/readyz`  | Readiness (checks Postgres + Chatwoot reachable) |

---

## 11. Environment variables

```env
# Etnia Bot API
APP_ENV=production                         # dev|staging|production
LOG_LEVEL=INFO

# Postgres (Supabase)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini                   # promote to newer model later

# Chatwoot
CHATWOOT_BASE_URL=https://crm.etniaviajes.com.ar
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_BOT_ACCESS_TOKEN=...              # from Agent Bot setup
CHATWOOT_WEBHOOK_SECRET=...                # shared secret we verify on inbound (added via Chatwoot webhook header, optional)

# Google Drive (ad/funnel config — still used)
SERVICE_ACCOUNT_FILE=/etc/secrets/gdrive.json
ADS_FILE_PATH=/etc/secrets/ads.json
OFFERS_DB_PATH=/etc/secrets/offers.json    # legacy; removed after Phase E migrates JSON → offers table
FOLDER_ID=...
FOLDER_ID_SEASONAL=...
FOLDER_ID_GRUPAL=...

# Webpage Supabase (read-only access to destinations + multidestination_packages)
WEB_SUPABASE_URL=https://<web-project>.supabase.co
WEB_SUPABASE_ANON_KEY=...

# App tuning
BOT_MAX_TURNS=10
BOT_TIMEOUT_HOURS=1
LLM_HISTORY_WINDOW=30
```

**Gone:** `REDIS_*`, `WORKER_REDIS_*`, `GOOGLE_SHEETS_*`, `WPP_ADAPTER_URL`, `AUTH_SESSION_KEY`.

---

## 12. Implementation plan (phases B–F)

Each phase is a self-contained branch + PR + deploy. A phase leaves `main` in a working state.

### Phase B — Foundation (≈ 3 days)

**Goal:** introduce Postgres, tests, and tooling; no behaviour change to the bot yet.

Tasks:

1. `requirements.txt` → add `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx` (test client). Pin versions.
2. Create `pyproject.toml` (black, ruff, mypy config).
3. Create Supabase project, grab `DATABASE_URL`. Store in new `.env.example`.
4. `alembic init alembic`, configure `alembic/env.py` to use async engine.
5. Write `app/domain/models.py` with SQLAlchemy models matching §7.2 DDL.
6. Write `alembic/versions/0001_initial.py` migration. Verify up/down on a clean DB.
7. Rename `pre_clasifyer_service.py` → `pre_classifier_service.py`. Update imports.
8. Rename `wpp_clinet_lifespan` → `client_lifespan`.
9. Fix `app/services/__init.py` → `__init__.py`.
10. Collapse `TotalStates` into `SessionState.label` property. Update `redis_services.py` call site (to be deleted in C anyway, but do the symbol fix here).
11. Wrap `config.py` classes in `@lru_cache` getters; no top-level instantiation.
12. Move `celery_writer.ipynb` to `notebooks/` (not tracked by git).
13. Move `reproduce_issue.py` to `scripts/`.
14. Scaffold `tests/unit/test_enums.py`, `tests/unit/test_iata.py`, `tests/integration/conftest.py` with an ephemeral Postgres fixture.
15. CI: add `.github/workflows/ci.yml` running ruff + mypy + pytest.

**Definition of done:** `alembic upgrade head` succeeds on a fresh Supabase DB; `pytest` runs green; bot still responds on WhatsApp unchanged.

### Phase C — Channel abstraction via Chatwoot (≈ 5 days)

**Goal:** replace the WhatsApp-only webhook with the Chatwoot webhook. Kill Redis, Celery, and Sheets.

Tasks:

1. Spin up Chatwoot on Hetzner per `docs/CHATWOOT_SETUP.md`. Connect one channel (WhatsApp via WPPConnect bridge for now — Cloud API migration is a separate effort).
2. Create Agent Bot in Chatwoot; copy `CHATWOOT_BOT_ACCESS_TOKEN`.
3. Write `app/integrations/chatwoot.py`: `ChatwootClient` with async methods `send_message`, `send_private_note`, `apply_labels`, `toggle_status`, `get_conversation`.
4. Write `app/domain/schemas.py`:
   ```python
   @dataclass
   class IncomingMessage:
       channel: Channel
       chatwoot_conversation_id: int
       chatwoot_contact_id: int
       external_user_id: str
       text: str
       sender_name: str | None
       received_at: datetime
       raw: dict
   ```
5. Write `app/domain/repositories.py`: `ContactRepo`, `ConversationRepo`, `BotStateRepo`, `QualificationEventRepo`. All async, single-session pattern.
6. Rewrite `app/services/chatbot_service.py`:
   - Signature: `process_message(msg: IncomingMessage, session: AsyncSession) -> None`.
   - Load/create contact + conversation via repos.
   - Load bot_state (or create with defaults).
   - Existing logic (guard → classifier → dispatcher → LLM) moves verbatim to new shape.
   - Replace `send_whatsapp_text(from_number, ...)` with `chatwoot_client.send_message(conversation_id, ...)`.
7. New router `app/api/routers/chatwoot_webhook.py`:
   - Verify `api_access_token` header matches `CHATWOOT_BOT_ACCESS_TOKEN`.
   - Ignore events where `message_type != "incoming"` or conversation already `status != "bot"`.
   - Build `IncomingMessage` from payload.
   - Call `ChatbotService.process_message`.
   - Return `200` within 5s (bot work can run in a background task if slow).
8. Delete `app/celery_app.py`, `app/tasks.py`, `app/services/redis_services.py`, `app/services/sheets_services.py`, `app/services/session_service.py`, `app/database/`, `app/api/routers/sheets_router.py`, `app/api/master_router.py`, `app/utils/whatsapp.py`, `app/api/routers/webhook_router.py`.
9. Update `app/app.py` lifespan: init SQLAlchemy engine, init `ChatwootClient`, teardown both.
10. Update `Dockerfile` entrypoint: `uvicorn app.app:app --host 0.0.0.0 --port 8000`.
11. Write `docker-compose.yml` for local dev (api + postgres + ngrok-or-equivalent).
12. Unit tests: mock `ChatwootClient`, drive `ChatbotService` through each state transition. Cover: new session → present offers → accept → handoff (with 3 expected ChatwootClient calls).

**Definition of done:** Chatwoot sends a `message_created` to the bot; bot replies through Chatwoot; Chatwoot delivers to WhatsApp. Old `/webhook/` endpoint is gone. Postgres has a `contact`, `conversation`, `bot_state`, and at least one `qualification_event` row per real conversation.

### Phase D — Handoff & agent workflow (≈ 2 days)

**Goal:** make the handoff states actually hand off usefully inside Chatwoot.

Tasks:

1. In `ChatbotService`, extract a `_handoff(conversation, new_state)` method that:
   - Composes the private-note summary.
   - Calls `chatwoot_client.send_private_note(...)`.
   - Calls `chatwoot_client.apply_labels([state.label_slug])`.
   - Calls `chatwoot_client.toggle_status(conversation_id, status="open")` and/or assigns to an inbox team.
   - Inserts a `qualification_event(type='handoff', payload={...})`.
   - Sets `conversation.status = 'handed_off'`, `conversation.closed_at = now()` (optional — keep open so agent can reply in Chatwoot).
2. In the Chatwoot webhook handler, **skip bot processing** if `conversation.status != 'bot'`.
3. Add a `conversation_updated` handler so when an agent applies the `bot-takeover` label, we flip `status='bot'` back.
4. Integration test: send a "yes I accept" message, assert 4 Chatwoot API calls in order.
5. Decision on `PreClasifyerService` fail-closed (see §16 open decisions).

**Definition of done:** agents see the qualified-lead summary as a private note when they open the conversation. They can reply in Chatwoot. Bot stays silent until released.

### Phase E — Data migration (≈ 1.5 days)

**Goal:** seed Postgres from (a) the existing Google Sheet so historical leads aren't lost and (b) the on-disk JSON offers file so the bot reads its catalog from the DB.

Tasks:

1. `scripts/migrate_from_sheets.py`:
   - Read the sheet via the existing `SheetsService` (temporarily kept for this script).
   - For each row: upsert `contacts` (match by phone), create `external_accounts(channel='whatsapp', external_id=phone)`, create `conversations(status='closed', channel='whatsapp', qualification=...)`, create a single synthesized `messages` note inside Chatwoot via API.
   - Idempotent (re-running produces no duplicates). Use `ON CONFLICT DO NOTHING` on `external_accounts.(channel, external_id)`.
2. Dry-run mode (`--dry-run`) that logs what would be written without committing.
3. Run on a Supabase staging branch. Verify counts.
4. Run on prod DB. Back up first (`pg_dump`).
5. Remove the remnants of `sheets_services.py` after migration confirmed.
6. Add `app/integrations/web_catalog.py` (`WebCatalogClient`) — read-only `httpx.AsyncClient` against the webpage Supabase REST API. Methods: `get_destination(id)`, `get_package(id)`, `list_destinations()`. Auth via `WEB_SUPABASE_ANON_KEY` header.
7. `scripts/migrate_offers_from_json.py`: parse `OFFERS_DB_PATH` (and `ADS_FILE_PATH` for the ad → key map). For each entry, upsert into `offers` keyed on `key`. Resolve `destination_id` / `package_id` via `WebCatalogClient`; fall back to `NULL` + log a warning when no match. Idempotent on the `offers.key` unique constraint.
8. `scripts/reconcile_offers.py`: nightly job. For every active offer, refresh denormalized fields (`destination_name`, `destination_slug`, `country`) from the webpage Supabase; log offers whose `destination_id` / `package_id` no longer resolves. Does **not** auto-deactivate — surfaces to a human.
9. Switch `chatbot_service` offer lookup from JSON file to `OfferRepo` (`get_by_key`, `list_active`). Once verified, delete `OFFERS_DB_PATH` env var and the on-disk `offers.json`.

**Definition of done:** every phone number in the Sheet exists as a contact in Postgres with a closed conversation and qualification data. Every offer the bot used to read from JSON exists as a row in `offers`, with denormalized fields populated. Migration scripts are idempotent.

### Phase F — Hardening & observability (≈ 3 days)

**Goal:** production-ready.

Tasks:

1. Structured logging with `structlog` or Python's `logging.config.dictConfig`; PII redaction on message bodies longer than N chars.
2. Rate limiting on `/webhooks/chatwoot` with `slowapi` (100 req/s/IP).
3. `/healthz` and `/readyz` endpoints.
4. Sentry integration (free tier) for error tracking.
5. Rebuild IATA city resolution (O1/O2):
   - Use `unicodedata` to fold accents.
   - Replace the nested-dict-with-duplicates with a flat list of `(iata, canonical, aliases, region)`.
   - Resolve in three passes: exact canonical, exact alias, fuzzy (`rapidfuzz` with ≥85 score).
   - Tests: table-driven, 50+ real phrases Etnia agents would see.
6. Pin Python version in `Dockerfile` (e.g. `python:3.12-slim`).
7. Set up daily Postgres backup (Supabase handles this on paid; on free, pg_dump + rclone to B2).
8. Document runbook (`docs/RUNBOOK.md`): "bot down" / "Chatwoot down" / "Postgres down" / "OpenAI quota" scenarios.

**Definition of done:** green CI, Sentry capturing errors, rate limit demonstrable, IATA tests pass, backup verified by restoring to a scratch DB.

---

## 13. Testing strategy

### 13.1 Unit (fast, no I/O)

- `tests/unit/test_enums.py` — labels correct, handoff_states complete.
- `tests/unit/test_iata.py` — 50+ phrase → IATA cases, after F5.
- `tests/unit/test_message_manager.py` — offer lookup, normalize_text accent folding.
- `tests/unit/test_chatbot_service.py` — with mocked `ChatwootClient`, `LLMExtractionService`, `PreClassifierService`; cover every state transition in the §8 state machine.

### 13.2 Integration (Postgres required)

- `tests/integration/test_repos.py` — upsert contact, idempotency of external_accounts unique constraint.
- `tests/integration/test_webhook.py` — `POST /webhooks/chatwoot` with realistic Chatwoot payloads, assert DB state + mocked Chatwoot API calls.

### 13.3 Smoke (manual, against staging)

- Send real WA/IG/FB messages to the staging Chatwoot inbox. Walk through each state-machine path.

### 13.4 Contract tests (Phase F nice-to-have)

- Pact-style test that our `ChatwootClient` methods send the exact payloads Chatwoot's API docs specify.

---

## 14. Data migration from Sheets

Only the summary data survives (see §5.5 in prior review). Concrete mapping:

| Sheet column          | Target field                                                           |
| --------------------- | ---------------------------------------------------------------------- |
| FECHA                 | `conversations.opened_at`                                              |
| TELEFONO              | `external_accounts.external_id` (channel=whatsapp), `contacts.phone`   |
| NOMBRE + APELLIDO     | `contacts.full_name`                                                   |
| DESTINO               | `conversations.destination`                                            |
| SALIDA DETECTADA      | `conversations.qualification.departure_iata`                           |
| FECHA DEL VIAJE       | `conversations.qualification.travel_month`                             |
| CANTIDAD DE PASAJEROS | `conversations.qualification.travelers_raw`                            |
| RESUMEN DE VIAJE      | single Chatwoot message of type `note` on the synthesized conversation |
| ESTADO                | mapped to `bot_state` + `status='closed'`                              |
| RED SOCIAL            | `conversations.channel` (WHATSAPP → whatsapp)                          |

Script is idempotent via `(channel, external_id)` unique constraint.

---

## 15. Risks & mitigations

| Risk                                         | Impact                             | Likelihood                                                      | Mitigation                                                                                                                          |
| -------------------------------------------- | ---------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| WhatsApp WPPConnect number gets banned       | Loses the only live channel        | Medium                                                          | Migrate to WhatsApp Cloud API before go-live (separate ~1 week effort). Meanwhile: production uses a dedicated disposable SIM card. |
| Meta App Review rejects IG/FB permissions    | No IG/FB until resolved            | Medium                                                          | Keep bot usable with WhatsApp alone while review iterates. App Review iterations take 3–15 days.                                    |
| Chatwoot self-host goes down                 | Whole pipeline down                | Low (once stabilized)                                           | Daily DB dumps offsite + documented one-command restore. UptimeRobot alert.                                                         |
| Supabase free-tier DB hits 500MB             | Queries slow / writes fail         | Low at current volume (1000s of rows/month = years of headroom) | Monitor DB size; upgrade to Pro ($25/mo) if approached.                                                                             |
| OpenAI outage                                | Bot silent or fail-closed          | Low                                                             | Fall back to friendly "our team will reply shortly" and enqueue a handoff.                                                          |
| Webhook signature/token leaks                | Attacker drives bot, burns credits | Medium if URL leaks                                             | Bot token required; rotate if leaked; rate limiting on `/webhooks/chatwoot`.                                                        |
| Migration script double-inserts              | Duplicate contacts                 | Low                                                             | Unique constraints + `ON CONFLICT DO NOTHING`; dry-run first.                                                                       |
| Chatwoot conversation.channel mapping drifts | Wrong channel labels in our DB     | Low                                                             | `tenant_config.channel_map` table as source of truth, re-validated at startup.                                                      |

---

## 16. Open decisions (needed before Phase B)

### Decided since 2026-04-23

- **Webpage catalog stays on its own Supabase project.** `destinations` and `multidestination_packages` are owned by the web team and not migrated into the CRM project. The bot reads them via the webpage project's REST API (`WebCatalogClient`) and denormalizes a few fields into `offers` for offline access. No cross-project FK; app-level validation on insert/update + nightly reconciliation. Documented in §7.2 (offers table), §9 (`integrations/web_catalog.py`), and §11 (`WEB_SUPABASE_*` env vars).
- **`tenant_config` is for Chatwoot connection settings, not multi-tenancy.** Single-row table holding Chatwoot base URL / account id / inbox→channel map. The name predates the multi-tenant decision in §0 and is a misnomer. Renaming to `chatwoot_config` is cosmetic — deferred to Phase F or never.
- **`qualification_events` is an append-only audit log of bot activity, not the travel-data store.** Travel fields (destination, travelers, dates, departure city) live denormalized on `conversations` + the `qualification` jsonb. The events table just lets you replay/debug what the bot did. Optional in v1 if audit isn't a priority — drop it without consequences to live behaviour.

### Decided since 2026-04-25

- **CRM Supabase project provisioned.** `DATABASE_URL` set in local `.env`. `pgcrypto` extension confirmed enabled. Phase B Alembic migrations can run against it.
- **Bot host: existing AWS EC2 instance** (replaces the Hetzner CX22 recommendation in §0 / §6.2). Same architecture — Chatwoot + bot piggyback on a single VPS — different provider.
  - Instance: `c7i-flex.large` (2 vCPU, 4 GB RAM) in `eu-west-1`. Already runs the legacy bot.
  - Disk: 8 GB EBS root → must be resized to ≥30 GB before Phase C (online resize via `growpart` + `resize2fs`).
  - Swap: 2 GB swapfile added as belt-and-suspenders for the 4 GB RAM ceiling.
  - Region note: `eu-west-1` adds ~150–200 ms latency for AR users vs `sa-east-1`. Accepted to avoid region migration on top of the architecture rework. Tracked as a future optimization.
  - Phase C ordering constraint: Chatwoot deploy and the kill of bot-side Redis + Celery + Sheets must happen in the **same** maintenance window. Running both stacks side-by-side risks OOM at ~3.6 GB combined RSS.
- **`PreClasifyerService` fail mode: fail-closed.** On OpenAI errors the message is dropped silently. Chosen against the §16 recommendation; the operational risk (real customer messages lost during OpenAI outages) is accepted. Phase D will still add a structured log + qualification_event so dropped messages are auditable, but no automated handoff or fallback reply.

### Open

1. **Bot host for FastAPI** — Supabase only hosts the DB. Where does the Python API run? Options:
   - **Fly.io** (free tier: 3 shared-cpu-1x 256MB VMs — tight but workable for this load).
   - **Render** (free web service, spins down after 15 min idle — adds latency on first request after idle).
   - **Same Hetzner VPS as Chatwoot** (add another Docker Compose service; free since the box is already there).
   - **Recommendation:** piggyback on the Hetzner box for Phase B. Move to Fly.io in Phase F if we want isolation.

2. **`PreClasifyerService` fail mode** — currently fail-closed (OpenAI error → drop message). I recommend **fail-open**: assume `is_travel_related=true, is_safe=true` on transient LLM errors, log it, and let the downstream flow handle the message. The worst case is an occasional borderline message getting through; better than silently dropping real customers.
   - **Needs your approval before Phase D.**

3. **Bot re-engagement after human handoff** — do we want a "re-activate bot" path (agent label `bot-takeover`), or is handoff strictly one-way?
   - **Recommendation:** start strictly one-way. Add the label-based re-activation in Phase F if agents request it.

4. **WhatsApp transport** — stay on WPPConnect for Phase B-D and cut over to Cloud API in Phase F, or do the Cloud API migration as Phase A.5 before anything else?
   - **Recommendation:** keep WPPConnect through Phase E (don't conflate two migrations); Cloud API migration is its own phase after cutover is stable.

5. **OpenAI model upgrade** — current `gpt-4o-mini`. Cheap and fast but outdated. Newer models at similar price tier available. Worth benchmarking in Phase F.
   - **Recommendation:** not a Phase B-E blocker. Queue for F.

6. **Notification to agents on handoff** — Chatwoot sends in-app notifications by default. Do we want Slack/email too?
   - **Recommendation:** default on Chatwoot alone for v1. Add Slack webhook in F if agents aren't responsive enough.

---

## Sign-off checklist before Phase B starts

- [ ] §0 summary matches your understanding of scope.
- [ ] §6 architecture diagrams match your mental model.
- [ ] §7 Postgres schema has everything you need (no missing fields for reporting/CRM flows you care about).
- [ ] §12 phase breakdown and effort estimates are reasonable.
- [ ] §16 open decisions answered (esp. #1 bot host and #2 fail mode).

Once signed off, Phase B starts with Alembic + Supabase provisioning and domain models — nothing user-visible breaks until Phase C.
