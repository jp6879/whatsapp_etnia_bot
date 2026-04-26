"""Initial CRM schema for Supabase Postgres.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE TYPE channel AS ENUM ('whatsapp', 'instagram', 'facebook');")
    op.execute("CREATE TYPE conversation_status AS ENUM ('bot', 'handed_off', 'closed');")
    op.execute(
        """
        CREATE TYPE session_state AS ENUM (
            'presenting_offers',
            'extracting_information',
            'handoff_with_offer',
            'handoff_no_offer',
            'handoff_timeout',
            'handoff_unknown_destination'
        );
        """
    )
    op.execute("CREATE TYPE deal_stage AS ENUM ('lead', 'quoted', 'booked', 'paid', 'lost');")

    op.execute(
        """
        CREATE TABLE tenant_config (
            id smallint PRIMARY KEY CHECK (id = 1),
            chatwoot_base_url text NOT NULL,
            chatwoot_account_id text NOT NULL,
            channel_map jsonb NOT NULL DEFAULT '{}',
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE contacts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            full_name text,
            email text,
            phone text,
            chatwoot_contact_id int UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX contacts_phone_idx ON contacts (phone) WHERE phone IS NOT NULL;")

    op.execute(
        """
        CREATE TABLE external_accounts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            contact_id uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            channel channel NOT NULL,
            external_id text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (channel, external_id)
        );
        """
    )

    op.execute(
        """
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
        """
    )
    op.execute("CREATE INDEX conversations_contact_idx ON conversations (contact_id);")
    op.execute("CREATE INDEX conversations_status_idx ON conversations (status);")

    op.execute(
        """
        CREATE TABLE bot_states (
            conversation_id uuid PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
            count_requests int NOT NULL DEFAULT 0,
            messages_history jsonb NOT NULL DEFAULT '[]',
            date_of_contact timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE qualification_events (
            id bigserial PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            event_type text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX qe_conv_idx ON qualification_events (conversation_id);")
    op.execute("CREATE INDEX qe_type_idx ON qualification_events (event_type);")

    op.execute(
        """
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
        """
    )

    op.execute(
        """
        CREATE TABLE agents (
            chatwoot_agent_id int PRIMARY KEY,
            name text NOT NULL,
            email text,
            role text,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE offers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            destination_id uuid,
            package_id uuid,
            key text NOT NULL UNIQUE,
            aliases text[] NOT NULL DEFAULT '{}',
            title text NOT NULL,
            summary_text text NOT NULL,
            destination_name text,
            destination_slug text,
            country text,
            price_from int,
            currency varchar(3),
            valid_from date,
            valid_until date,
            is_active boolean NOT NULL DEFAULT true,
            payload jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT offers_valid_window CHECK
                (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
        );
        """
    )
    op.execute("CREATE INDEX offers_active_idx ON offers (is_active) WHERE is_active;")
    op.execute("CREATE INDEX offers_destination_idx ON offers (destination_id);")
    op.execute("CREATE INDEX offers_package_idx ON offers (package_id);")
    op.execute("CREATE INDEX offers_key_lower_idx ON offers (lower(key));")
    op.execute("CREATE INDEX offers_aliases_gin_idx ON offers USING gin (aliases);")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER offers_set_updated_at
        BEFORE UPDATE ON offers
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS offers_set_updated_at ON offers;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
    op.execute("DROP TABLE IF EXISTS offers;")
    op.execute("DROP TABLE IF EXISTS agents;")
    op.execute("DROP TABLE IF EXISTS deals;")
    op.execute("DROP TABLE IF EXISTS qualification_events;")
    op.execute("DROP TABLE IF EXISTS bot_states;")
    op.execute("DROP TABLE IF EXISTS conversations;")
    op.execute("DROP TABLE IF EXISTS external_accounts;")
    op.execute("DROP TABLE IF EXISTS contacts;")
    op.execute("DROP TABLE IF EXISTS tenant_config;")
    op.execute("DROP TYPE IF EXISTS deal_stage;")
    op.execute("DROP TYPE IF EXISTS session_state;")
    op.execute("DROP TYPE IF EXISTS conversation_status;")
    op.execute("DROP TYPE IF EXISTS channel;")
