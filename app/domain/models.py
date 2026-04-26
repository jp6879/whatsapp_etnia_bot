from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Channel(enum.StrEnum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"


class ConversationStatus(enum.StrEnum):
    BOT = "bot"
    HANDED_OFF = "handed_off"
    CLOSED = "closed"


class BotSessionState(enum.StrEnum):
    PRESENTING_OFFERS = "presenting_offers"
    EXTRACTING_INFORMATION = "extracting_information"
    HANDOFF_WITH_OFFER = "handoff_with_offer"
    HANDOFF_NO_OFFER = "handoff_no_offer"
    HANDOFF_TIMEOUT = "handoff_timeout"
    HANDOFF_UNKNOWN_DESTINATION = "handoff_unknown_destination"


class DealStage(enum.StrEnum):
    LEAD = "lead"
    QUOTED = "quoted"
    BOOKED = "booked"
    PAID = "paid"
    LOST = "lost"


channel_enum = ENUM(Channel, name="channel", create_type=False)
conversation_status_enum = ENUM(
    ConversationStatus, name="conversation_status", create_type=False
)
session_state_enum = ENUM(BotSessionState, name="session_state", create_type=False)
deal_stage_enum = ENUM(DealStage, name="deal_stage", create_type=False)


class TenantConfig(Base):
    __tablename__ = "tenant_config"
    __table_args__ = (CheckConstraint("id = 1", name="tenant_config_singleton_check"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    chatwoot_base_url: Mapped[str] = mapped_column(Text, nullable=False)
    chatwoot_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    full_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    chatwoot_contact_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ExternalAccount(Base):
    __tablename__ = "external_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[Channel] = mapped_column(channel_enum, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False
    )
    channel: Mapped[Channel] = mapped_column(channel_enum, nullable=False)
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    status: Mapped[ConversationStatus] = mapped_column(
        conversation_status_enum, nullable=False, server_default=text("'bot'")
    )
    bot_state: Mapped[BotSessionState] = mapped_column(
        session_state_enum,
        nullable=False,
        server_default=text("'presenting_offers'"),
    )
    destination: Mapped[str | None] = mapped_column(Text)
    offer_type: Mapped[str | None] = mapped_column(Text)
    destination_key: Mapped[str | None] = mapped_column(Text)
    qualification: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_agent_id: Mapped[int | None] = mapped_column(Integer)


class BotState(Base):
    __tablename__ = "bot_states"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    count_requests: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    messages_history: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    date_of_contact: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class QualificationEvent(Base):
    __tablename__ = "qualification_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id")
    )
    stage: Mapped[DealStage] = mapped_column(
        deal_stage_enum, nullable=False, server_default=text("'lead'")
    )
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Agent(Base):
    __tablename__ = "agents"

    chatwoot_agent_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="offers_valid_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    destination_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    package_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    destination_name: Mapped[str | None] = mapped_column(Text)
    destination_slug: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    price_from: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
