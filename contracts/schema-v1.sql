-- contracts/schema-v1.sql — the schema at migration head (0017), generated with
-- pg_dump --schema-only from a migrated scratch database. Ports start from this
-- file (Flyway V1__baseline.sql / raw 001_baseline.sql) and mirror later
-- Alembic migrations as SQL (ADR 0012). Regenerate after every migration; see
-- ports/README.md. Monthly usage_events partitions reflect the dump date.
-- SQL-language functions are declared before the tables they reference, so a
-- runner must keep check_function_bodies off while applying this file.

SET check_function_bodies = false;

--
-- PostgreSQL database dump
--

--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

--
-- Name: synapse_org_for_invite_token(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.synapse_org_for_invite_token(p_hash text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
        SELECT organization_id FROM memberships
        WHERE invite_token_hash = p_hash AND status = 'invited'
        LIMIT 1
    $$;

--
-- Name: synapse_org_for_provider_ref(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.synapse_org_for_provider_ref(p_customer_id text, p_subscription_id text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
        SELECT organization_id FROM (
            SELECT organization_id, 1 AS rank FROM billing_customers
            WHERE p_customer_id IS NOT NULL AND provider_customer_id = p_customer_id
            UNION ALL
            SELECT organization_id, 2 FROM subscriptions
            WHERE p_subscription_id IS NOT NULL AND provider_subscription_id = p_subscription_id
        ) refs
        ORDER BY rank
        LIMIT 1
    $$;

--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    slug character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    status character varying(16) DEFAULT 'active'::character varying NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT ck_agents_ck_agents_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'disabled'::character varying])::text[])))
);

--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    prefix character varying(16) NOT NULL,
    key_hash character varying(64) NOT NULL,
    scopes text[] DEFAULT '{}'::text[] NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_by_user_id uuid,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id uuid NOT NULL,
    organization_id uuid,
    actor_user_id uuid,
    actor_type character varying(20) NOT NULL,
    event_type character varying(100) NOT NULL,
    target_type character varying(64),
    target_id uuid,
    diff jsonb,
    ip character varying(45),
    user_agent character varying(500),
    request_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: billing_customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.billing_customers (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    provider character varying(32) NOT NULL,
    provider_customer_id character varying(255),
    email character varying(320),
    name character varying(200),
    tax_id character varying(64),
    billing_address jsonb NOT NULL,
    currency character varying(3),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: entitlements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entitlements (
    organization_id uuid NOT NULL,
    id uuid NOT NULL,
    feature_key character varying(100) NOT NULL,
    source character varying(20) NOT NULL,
    enabled boolean NOT NULL,
    starts_at timestamp with time zone DEFAULT now() NOT NULL,
    ends_at timestamp with time zone,
    note text,
    created_by_user_id uuid,
    revoked_at timestamp with time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    limit_value bigint,
    CONSTRAINT ck_entitlements_ck_entitlements_source CHECK (((source)::text = ANY ((ARRAY['trial'::character varying, 'addon'::character varying, 'promo'::character varying, 'beta'::character varying, 'override'::character varying, 'enterprise'::character varying, 'grandfather'::character varying])::text[])))
);

--
-- Name: example_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.example_projects (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    title text NOT NULL
);

--
-- Name: feature_flag_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feature_flag_overrides (
    id uuid NOT NULL,
    flag_key character varying(100) NOT NULL,
    organization_id uuid,
    user_id uuid,
    enabled boolean NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT ck_feature_flag_overrides_ck_ff_override_scope CHECK (((organization_id IS NOT NULL) OR (user_id IS NOT NULL)))
);

--
-- Name: feature_flags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feature_flags (
    id uuid NOT NULL,
    key character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    enabled boolean DEFAULT false NOT NULL,
    rollout_percentage integer,
    archived_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT ck_feature_flags_ck_feature_flags_rollout CHECK (((rollout_percentage IS NULL) OR ((rollout_percentage >= 0) AND (rollout_percentage <= 100))))
);

--
-- Name: features; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.features (
    key character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    category character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: invoice_lines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoice_lines (
    id uuid NOT NULL,
    invoice_id uuid NOT NULL,
    kind character varying(16) NOT NULL,
    description text NOT NULL,
    quantity bigint DEFAULT '1'::bigint NOT NULL,
    unit_amount_cents bigint NOT NULL,
    amount_cents bigint NOT NULL,
    metric character varying(100),
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    organization_id uuid NOT NULL,
    CONSTRAINT ck_invoice_lines_ck_invoice_lines_kind CHECK (((kind)::text = ANY ((ARRAY['plan'::character varying, 'overage'::character varying, 'credit'::character varying, 'custom'::character varying])::text[])))
);

--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    billing_customer_id uuid,
    provider character varying(32),
    provider_invoice_id character varying(255),
    number character varying(64),
    currency character varying(3) NOT NULL,
    subtotal_cents bigint NOT NULL,
    tax_cents bigint NOT NULL,
    total_cents bigint NOT NULL,
    status character varying(20) NOT NULL,
    period_start timestamp with time zone,
    period_end timestamp with time zone,
    hosted_url text,
    pdf_url text,
    issued_at timestamp with time zone,
    paid_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_invoices_ck_invoices_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'open'::character varying, 'paid'::character varying, 'void'::character varying, 'uncollectible'::character varying])::text[])))
);

--
-- Name: membership_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.membership_roles (
    membership_id uuid NOT NULL,
    role_id uuid NOT NULL
);

--
-- Name: memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memberships (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid,
    invited_email public.citext,
    status character varying(20) NOT NULL,
    joined_at timestamp with time zone,
    permission_keys text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    invite_token_hash character varying(64),
    CONSTRAINT ck_memberships_ck_memberships_status_valid CHECK (((status)::text = ANY ((ARRAY['invited'::character varying, 'active'::character varying, 'suspended'::character varying])::text[]))),
    CONSTRAINT ck_memberships_ck_memberships_user_or_invite CHECK (((user_id IS NOT NULL) OR (invited_email IS NOT NULL)))
);

--
-- Name: metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metrics (
    key character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    kind character varying(20) NOT NULL,
    unit character varying(32),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    overage_unit integer,
    overage_price_cents bigint
);

--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid NOT NULL,
    slug character varying(64) NOT NULL,
    name character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    owner_user_id uuid,
    settings jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone
);

--
-- Name: outbox_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox_events (
    id uuid NOT NULL,
    aggregate_type character varying(64) NOT NULL,
    aggregate_id uuid NOT NULL,
    organization_id uuid,
    event_type character varying(100) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone,
    attempts integer NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    last_error text,
    audience character varying(16) DEFAULT 'public'::character varying NOT NULL,
    dead_at timestamp with time zone,
    CONSTRAINT ck_outbox_events_ck_outbox_events_audience CHECK (((audience)::text = ANY ((ARRAY['public'::character varying, 'internal'::character varying])::text[])))
);

--
-- Name: password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_reset_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    max_uses integer NOT NULL
);

--
-- Name: permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permissions (
    id uuid NOT NULL,
    key character varying(100) NOT NULL,
    resource character varying(64) NOT NULL,
    action character varying(64) NOT NULL,
    description text
);

--
-- Name: plan_features; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plan_features (
    plan_id uuid NOT NULL,
    feature_key character varying(100) NOT NULL,
    enabled boolean NOT NULL
);

--
-- Name: plan_limits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plan_limits (
    plan_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    limit_value bigint,
    soft_limit_ratio numeric(5,2),
    overage_unit integer,
    overage_price_cents bigint
);

--
-- Name: plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plans (
    id uuid NOT NULL,
    key character varying(64) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    price_cents bigint,
    currency character varying(3) NOT NULL,
    "interval" character varying(10),
    is_public boolean NOT NULL,
    is_custom boolean NOT NULL,
    trial_days integer NOT NULL,
    sort_order integer NOT NULL,
    provider_refs jsonb NOT NULL,
    metadata jsonb NOT NULL,
    archived_at timestamp with time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: provider_webhook_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provider_webhook_events (
    id uuid NOT NULL,
    provider character varying(32) NOT NULL,
    provider_event_id character varying(255) NOT NULL,
    event_type character varying(128),
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    error text
);

--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refresh_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    organization_id uuid,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    replaced_by_token_id uuid,
    user_agent character varying(500),
    ip character varying(45),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permissions (
    role_id uuid NOT NULL,
    permission_id uuid NOT NULL
);

--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id uuid NOT NULL,
    organization_id uuid,
    key character varying(64) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    is_system boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: stored_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stored_files (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    key character varying(512) NOT NULL,
    name character varying(255) NOT NULL,
    content_type character varying(128) NOT NULL,
    size_bytes bigint DEFAULT '0'::bigint NOT NULL,
    deleted_at timestamp with time zone,
    created_by_user_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    status character varying(16) DEFAULT 'ready'::character varying NOT NULL,
    CONSTRAINT ck_stored_files_ck_stored_files_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'ready'::character varying])::text[])))
);

--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscriptions (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    plan_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    current_period_start timestamp with time zone NOT NULL,
    current_period_end timestamp with time zone NOT NULL,
    trial_ends_at timestamp with time zone,
    cancel_at_period_end boolean NOT NULL,
    canceled_at timestamp with time zone,
    provider character varying(32),
    provider_subscription_id character varying(255),
    billing_customer_id uuid,
    plan_snapshot jsonb NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    pending_adjustments jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT ck_subscriptions_ck_subscriptions_status CHECK (((status)::text = ANY ((ARRAY['trialing'::character varying, 'active'::character varying, 'past_due'::character varying, 'canceled'::character varying, 'incomplete'::character varying, 'unpaid'::character varying])::text[])))
);

--
-- Name: usage_counters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_counters (
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    period_start date NOT NULL,
    quantity_total bigint NOT NULL,
    soft_limit_notified_at timestamp with time zone,
    last_event_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
)
PARTITION BY RANGE (occurred_at);

--
-- Name: usage_events_default; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events_default (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_events_y2026m09; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events_y2026m09 (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_events_y2026m10; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events_y2026m10 (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_events_y2026m11; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events_y2026m11 (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_events_y2026m12; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_events_y2026m12 (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key text,
    properties jsonb DEFAULT '{}'::jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_idempotency_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_idempotency_keys (
    organization_id uuid NOT NULL,
    idempotency_key character varying(255) NOT NULL,
    metric character varying(100) NOT NULL,
    quantity bigint NOT NULL,
    total_after bigint,
    event_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email public.citext NOT NULL,
    password_hash text,
    display_name character varying(200) NOT NULL,
    avatar_url text,
    is_platform_admin boolean NOT NULL,
    is_active boolean NOT NULL,
    last_login_at timestamp with time zone,
    identity_provider character varying(32) NOT NULL,
    provider_subject character varying(255),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: webhook_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_deliveries (
    id uuid NOT NULL,
    endpoint_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    outbox_event_id uuid,
    event_type character varying(100) NOT NULL,
    payload jsonb NOT NULL,
    status character varying(20) NOT NULL,
    attempts integer NOT NULL,
    max_attempts integer NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT now() NOT NULL,
    last_response_code integer,
    last_error text,
    response_excerpt text,
    delivered_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_webhook_deliveries_ck_webhook_deliveries_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'delivered'::character varying, 'failed'::character varying, 'exhausted'::character varying])::text[])))
);

--
-- Name: webhook_endpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_endpoints (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    url text NOT NULL,
    secret_encrypted bytea NOT NULL,
    description character varying(500),
    events text[] DEFAULT '{}'::text[] NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);

--
-- Name: usage_events_default; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events ATTACH PARTITION public.usage_events_default DEFAULT;

--
-- Name: usage_events_y2026m09; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events ATTACH PARTITION public.usage_events_y2026m09 FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');

--
-- Name: usage_events_y2026m10; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events ATTACH PARTITION public.usage_events_y2026m10 FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');

--
-- Name: usage_events_y2026m11; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events ATTACH PARTITION public.usage_events_y2026m11 FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');

--
-- Name: usage_events_y2026m12; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events ATTACH PARTITION public.usage_events_y2026m12 FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');

--
-- Name: agents pk_agents; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT pk_agents PRIMARY KEY (id);

--
-- Name: api_keys pk_api_keys; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT pk_api_keys PRIMARY KEY (id);

--
-- Name: audit_logs pk_audit_logs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT pk_audit_logs PRIMARY KEY (id);

--
-- Name: billing_customers pk_billing_customers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_customers
    ADD CONSTRAINT pk_billing_customers PRIMARY KEY (id);

--
-- Name: entitlements pk_entitlements; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entitlements
    ADD CONSTRAINT pk_entitlements PRIMARY KEY (id);

--
-- Name: example_projects pk_example_projects; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.example_projects
    ADD CONSTRAINT pk_example_projects PRIMARY KEY (id);

--
-- Name: feature_flag_overrides pk_feature_flag_overrides; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_flag_overrides
    ADD CONSTRAINT pk_feature_flag_overrides PRIMARY KEY (id);

--
-- Name: feature_flags pk_feature_flags; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_flags
    ADD CONSTRAINT pk_feature_flags PRIMARY KEY (id);

--
-- Name: features pk_features; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.features
    ADD CONSTRAINT pk_features PRIMARY KEY (key);

--
-- Name: invoice_lines pk_invoice_lines; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT pk_invoice_lines PRIMARY KEY (id);

--
-- Name: invoices pk_invoices; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT pk_invoices PRIMARY KEY (id);

--
-- Name: membership_roles pk_membership_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_roles
    ADD CONSTRAINT pk_membership_roles PRIMARY KEY (membership_id, role_id);

--
-- Name: memberships pk_memberships; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT pk_memberships PRIMARY KEY (id);

--
-- Name: metrics pk_metrics; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metrics
    ADD CONSTRAINT pk_metrics PRIMARY KEY (key);

--
-- Name: organizations pk_organizations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT pk_organizations PRIMARY KEY (id);

--
-- Name: outbox_events pk_outbox_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT pk_outbox_events PRIMARY KEY (id);

--
-- Name: password_reset_tokens pk_password_reset_tokens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT pk_password_reset_tokens PRIMARY KEY (id);

--
-- Name: permissions pk_permissions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT pk_permissions PRIMARY KEY (id);

--
-- Name: plan_features pk_plan_features; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_features
    ADD CONSTRAINT pk_plan_features PRIMARY KEY (plan_id, feature_key);

--
-- Name: plan_limits pk_plan_limits; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_limits
    ADD CONSTRAINT pk_plan_limits PRIMARY KEY (plan_id, metric);

--
-- Name: plans pk_plans; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plans
    ADD CONSTRAINT pk_plans PRIMARY KEY (id);

--
-- Name: provider_webhook_events pk_provider_webhook_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_webhook_events
    ADD CONSTRAINT pk_provider_webhook_events PRIMARY KEY (id);

--
-- Name: refresh_tokens pk_refresh_tokens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT pk_refresh_tokens PRIMARY KEY (id);

--
-- Name: role_permissions pk_role_permissions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id);

--
-- Name: roles pk_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT pk_roles PRIMARY KEY (id);

--
-- Name: stored_files pk_stored_files; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_files
    ADD CONSTRAINT pk_stored_files PRIMARY KEY (id);

--
-- Name: subscriptions pk_subscriptions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT pk_subscriptions PRIMARY KEY (id);

--
-- Name: usage_counters pk_usage_counters; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_counters
    ADD CONSTRAINT pk_usage_counters PRIMARY KEY (organization_id, metric, period_start);

--
-- Name: usage_idempotency_keys pk_usage_idempotency_keys; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_idempotency_keys
    ADD CONSTRAINT pk_usage_idempotency_keys PRIMARY KEY (organization_id, idempotency_key);

--
-- Name: users pk_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);

--
-- Name: webhook_deliveries pk_webhook_deliveries; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT pk_webhook_deliveries PRIMARY KEY (id);

--
-- Name: webhook_endpoints pk_webhook_endpoints; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_endpoints
    ADD CONSTRAINT pk_webhook_endpoints PRIMARY KEY (id);

--
-- Name: agents uq_agents_org_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT uq_agents_org_slug UNIQUE (organization_id, slug);

--
-- Name: billing_customers uq_billing_customers_organization_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_customers
    ADD CONSTRAINT uq_billing_customers_organization_id UNIQUE (organization_id);

--
-- Name: billing_customers uq_billing_customers_provider_ref; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_customers
    ADD CONSTRAINT uq_billing_customers_provider_ref UNIQUE (provider, provider_customer_id);

--
-- Name: invoices uq_invoices_provider_ref; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT uq_invoices_provider_ref UNIQUE (provider, provider_invoice_id);

--
-- Name: memberships uq_memberships_org_invited_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT uq_memberships_org_invited_email UNIQUE (organization_id, invited_email);

--
-- Name: memberships uq_memberships_org_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT uq_memberships_org_user UNIQUE (organization_id, user_id);

--
-- Name: password_reset_tokens uq_password_reset_tokens_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT uq_password_reset_tokens_token_hash UNIQUE (token_hash);

--
-- Name: roles uq_roles_org_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_roles_org_key UNIQUE (organization_id, key);

--
-- Name: usage_events usage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT usage_events_pkey PRIMARY KEY (id, occurred_at);

--
-- Name: usage_events_default usage_events_default_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events_default
    ADD CONSTRAINT usage_events_default_pkey PRIMARY KEY (id, occurred_at);

--
-- Name: usage_events_y2026m09 usage_events_y2026m09_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events_y2026m09
    ADD CONSTRAINT usage_events_y2026m09_pkey PRIMARY KEY (id, occurred_at);

--
-- Name: usage_events_y2026m10 usage_events_y2026m10_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events_y2026m10
    ADD CONSTRAINT usage_events_y2026m10_pkey PRIMARY KEY (id, occurred_at);

--
-- Name: usage_events_y2026m11 usage_events_y2026m11_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events_y2026m11
    ADD CONSTRAINT usage_events_y2026m11_pkey PRIMARY KEY (id, occurred_at);

--
-- Name: usage_events_y2026m12 usage_events_y2026m12_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_events_y2026m12
    ADD CONSTRAINT usage_events_y2026m12_pkey PRIMARY KEY (id, occurred_at);

--
-- Name: ix_agents_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_org_status ON public.agents USING btree (organization_id, status);

--
-- Name: ix_agents_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_organization_id ON public.agents USING btree (organization_id);

--
-- Name: ix_api_keys_key_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_api_keys_key_hash ON public.api_keys USING btree (key_hash);

--
-- Name: ix_api_keys_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_organization_id ON public.api_keys USING btree (organization_id);

--
-- Name: ix_api_keys_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_api_keys_prefix ON public.api_keys USING btree (prefix);

--
-- Name: ix_audit_logs_created_brin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_brin ON public.audit_logs USING brin (created_at);

--
-- Name: ix_audit_logs_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_event_type ON public.audit_logs USING btree (event_type);

--
-- Name: ix_audit_logs_org_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_org_created ON public.audit_logs USING btree (organization_id, created_at);

--
-- Name: ix_audit_logs_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_organization_id ON public.audit_logs USING btree (organization_id);

--
-- Name: ix_audit_logs_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_request_id ON public.audit_logs USING btree (request_id);

--
-- Name: ix_entitlements_feature_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entitlements_feature_key ON public.entitlements USING btree (feature_key);

--
-- Name: ix_entitlements_org_feature_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entitlements_org_feature_active ON public.entitlements USING btree (organization_id, feature_key) WHERE (revoked_at IS NULL);

--
-- Name: ix_entitlements_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_entitlements_organization_id ON public.entitlements USING btree (organization_id);

--
-- Name: ix_example_projects_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_example_projects_organization_id ON public.example_projects USING btree (organization_id);

--
-- Name: ix_feature_flag_overrides_flag_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_feature_flag_overrides_flag_key ON public.feature_flag_overrides USING btree (flag_key);

--
-- Name: ix_feature_flag_overrides_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_feature_flag_overrides_organization_id ON public.feature_flag_overrides USING btree (organization_id);

--
-- Name: ix_feature_flag_overrides_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_feature_flag_overrides_user_id ON public.feature_flag_overrides USING btree (user_id);

--
-- Name: ix_feature_flags_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_feature_flags_key ON public.feature_flags USING btree (key);

--
-- Name: ix_invoice_lines_invoice_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoice_lines_invoice_id ON public.invoice_lines USING btree (invoice_id);

--
-- Name: ix_invoice_lines_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoice_lines_kind ON public.invoice_lines USING btree (kind);

--
-- Name: ix_invoice_lines_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoice_lines_organization_id ON public.invoice_lines USING btree (organization_id);

--
-- Name: ix_invoices_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_invoices_organization_id ON public.invoices USING btree (organization_id);

--
-- Name: ix_memberships_invite_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memberships_invite_token_hash ON public.memberships USING btree (invite_token_hash);

--
-- Name: ix_memberships_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memberships_organization_id ON public.memberships USING btree (organization_id);

--
-- Name: ix_memberships_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_memberships_user_id ON public.memberships USING btree (user_id);

--
-- Name: ix_organizations_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_organizations_slug ON public.organizations USING btree (slug);

--
-- Name: ix_outbox_events_aggregate_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_aggregate_type ON public.outbox_events USING btree (aggregate_type);

--
-- Name: ix_outbox_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_event_type ON public.outbox_events USING btree (event_type);

--
-- Name: ix_outbox_events_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_organization_id ON public.outbox_events USING btree (organization_id);

--
-- Name: ix_outbox_events_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_pending ON public.outbox_events USING btree (next_attempt_at) WHERE ((published_at IS NULL) AND (dead_at IS NULL));

--
-- Name: ix_outbox_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_pending ON public.outbox_events USING btree (next_attempt_at) WHERE (published_at IS NULL);

--
-- Name: ix_password_reset_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_user_id ON public.password_reset_tokens USING btree (user_id);

--
-- Name: ix_permissions_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_permissions_key ON public.permissions USING btree (key);

--
-- Name: ix_plans_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_plans_key ON public.plans USING btree (key);

--
-- Name: ix_refresh_tokens_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON public.refresh_tokens USING btree (token_hash);

--
-- Name: ix_refresh_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);

--
-- Name: ix_roles_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_roles_organization_id ON public.roles USING btree (organization_id);

--
-- Name: ix_stored_files_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stored_files_key ON public.stored_files USING btree (key);

--
-- Name: ix_stored_files_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stored_files_organization_id ON public.stored_files USING btree (organization_id);

--
-- Name: ix_stored_files_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_stored_files_pending ON public.stored_files USING btree (created_at) WHERE (((status)::text = 'pending'::text) AND (deleted_at IS NULL));

--
-- Name: ix_subscriptions_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscriptions_organization_id ON public.subscriptions USING btree (organization_id);

--
-- Name: ix_subscriptions_plan_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscriptions_plan_id ON public.subscriptions USING btree (plan_id);

--
-- Name: ix_usage_events_occurred_brin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_events_occurred_brin ON ONLY public.usage_events USING brin (occurred_at);

--
-- Name: ix_usage_events_org_metric_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_events_org_metric_time ON ONLY public.usage_events USING btree (organization_id, metric, occurred_at);

--
-- Name: ix_usage_idempotency_keys_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_idempotency_keys_created_at ON public.usage_idempotency_keys USING btree (created_at);

--
-- Name: ix_usage_idempotency_keys_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_idempotency_keys_organization_id ON public.usage_idempotency_keys USING btree (organization_id);

--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);

--
-- Name: ix_webhook_deliveries_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_due ON public.webhook_deliveries USING btree (next_attempt_at) WHERE ((status)::text = 'pending'::text);

--
-- Name: ix_webhook_deliveries_endpoint_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_endpoint_id ON public.webhook_deliveries USING btree (endpoint_id);

--
-- Name: ix_webhook_deliveries_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_event_type ON public.webhook_deliveries USING btree (event_type);

--
-- Name: ix_webhook_deliveries_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_organization_id ON public.webhook_deliveries USING btree (organization_id);

--
-- Name: ix_webhook_endpoints_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_endpoints_organization_id ON public.webhook_endpoints USING btree (organization_id);

--
-- Name: uq_invoices_org_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_invoices_org_number ON public.invoices USING btree (organization_id, number) WHERE (number IS NOT NULL);

--
-- Name: uq_provider_webhook_events_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_provider_webhook_events_ref ON public.provider_webhook_events USING btree (provider, provider_event_id);

--
-- Name: uq_subscriptions_one_per_org; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_subscriptions_one_per_org ON public.subscriptions USING btree (organization_id) WHERE ((status)::text = ANY ((ARRAY['trialing'::character varying, 'active'::character varying, 'past_due'::character varying])::text[]));

--
-- Name: uq_subscriptions_provider_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_subscriptions_provider_ref ON public.subscriptions USING btree (provider, provider_subscription_id) WHERE (provider_subscription_id IS NOT NULL);

--
-- Name: uq_usage_events_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_usage_events_idempotency ON ONLY public.usage_events USING btree (organization_id, metric, idempotency_key, occurred_at) WHERE (idempotency_key IS NOT NULL);

--
-- Name: usage_events_default_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_default_occurred_at_idx ON public.usage_events_default USING brin (occurred_at);

--
-- Name: usage_events_default_organization_id_metric_idempotency_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usage_events_default_organization_id_metric_idempotency_key_idx ON public.usage_events_default USING btree (organization_id, metric, idempotency_key, occurred_at) WHERE (idempotency_key IS NOT NULL);

--
-- Name: usage_events_default_organization_id_metric_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_default_organization_id_metric_occurred_at_idx ON public.usage_events_default USING btree (organization_id, metric, occurred_at);

--
-- Name: usage_events_y2026m09_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m09_occurred_at_idx ON public.usage_events_y2026m09 USING brin (occurred_at);

--
-- Name: usage_events_y2026m09_organization_id_metric_idempotency_ke_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usage_events_y2026m09_organization_id_metric_idempotency_ke_idx ON public.usage_events_y2026m09 USING btree (organization_id, metric, idempotency_key, occurred_at) WHERE (idempotency_key IS NOT NULL);

--
-- Name: usage_events_y2026m09_organization_id_metric_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m09_organization_id_metric_occurred_at_idx ON public.usage_events_y2026m09 USING btree (organization_id, metric, occurred_at);

--
-- Name: usage_events_y2026m10_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m10_occurred_at_idx ON public.usage_events_y2026m10 USING brin (occurred_at);

--
-- Name: usage_events_y2026m10_organization_id_metric_idempotency_ke_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usage_events_y2026m10_organization_id_metric_idempotency_ke_idx ON public.usage_events_y2026m10 USING btree (organization_id, metric, idempotency_key, occurred_at) WHERE (idempotency_key IS NOT NULL);

--
-- Name: usage_events_y2026m10_organization_id_metric_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m10_organization_id_metric_occurred_at_idx ON public.usage_events_y2026m10 USING btree (organization_id, metric, occurred_at);

--
-- Name: usage_events_y2026m11_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m11_occurred_at_idx ON public.usage_events_y2026m11 USING brin (occurred_at);

--
-- Name: usage_events_y2026m11_organization_id_metric_idempotency_ke_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usage_events_y2026m11_organization_id_metric_idempotency_ke_idx ON public.usage_events_y2026m11 USING btree (organization_id, metric, idempotency_key, occurred_at) WHERE (idempotency_key IS NOT NULL);

--
-- Name: usage_events_y2026m11_organization_id_metric_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m11_organization_id_metric_occurred_at_idx ON public.usage_events_y2026m11 USING btree (organization_id, metric, occurred_at);

--
-- Name: usage_events_y2026m12_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m12_occurred_at_idx ON public.usage_events_y2026m12 USING brin (occurred_at);

--
-- Name: usage_events_y2026m12_organization_id_metric_idempotency_ke_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX usage_events_y2026m12_organization_id_metric_idempotency_ke_idx ON public.usage_events_y2026m12 USING btree (organization_id, metric, idempotency_key, occurred_at) WHERE (idempotency_key IS NOT NULL);

--
-- Name: usage_events_y2026m12_organization_id_metric_occurred_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX usage_events_y2026m12_organization_id_metric_occurred_at_idx ON public.usage_events_y2026m12 USING btree (organization_id, metric, occurred_at);

--
-- Name: usage_events_default_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_occurred_brin ATTACH PARTITION public.usage_events_default_occurred_at_idx;

--
-- Name: usage_events_default_organization_id_metric_idempotency_key_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.uq_usage_events_idempotency ATTACH PARTITION public.usage_events_default_organization_id_metric_idempotency_key_idx;

--
-- Name: usage_events_default_organization_id_metric_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_org_metric_time ATTACH PARTITION public.usage_events_default_organization_id_metric_occurred_at_idx;

--
-- Name: usage_events_default_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.usage_events_pkey ATTACH PARTITION public.usage_events_default_pkey;

--
-- Name: usage_events_y2026m09_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_occurred_brin ATTACH PARTITION public.usage_events_y2026m09_occurred_at_idx;

--
-- Name: usage_events_y2026m09_organization_id_metric_idempotency_ke_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.uq_usage_events_idempotency ATTACH PARTITION public.usage_events_y2026m09_organization_id_metric_idempotency_ke_idx;

--
-- Name: usage_events_y2026m09_organization_id_metric_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_org_metric_time ATTACH PARTITION public.usage_events_y2026m09_organization_id_metric_occurred_at_idx;

--
-- Name: usage_events_y2026m09_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.usage_events_pkey ATTACH PARTITION public.usage_events_y2026m09_pkey;

--
-- Name: usage_events_y2026m10_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_occurred_brin ATTACH PARTITION public.usage_events_y2026m10_occurred_at_idx;

--
-- Name: usage_events_y2026m10_organization_id_metric_idempotency_ke_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.uq_usage_events_idempotency ATTACH PARTITION public.usage_events_y2026m10_organization_id_metric_idempotency_ke_idx;

--
-- Name: usage_events_y2026m10_organization_id_metric_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_org_metric_time ATTACH PARTITION public.usage_events_y2026m10_organization_id_metric_occurred_at_idx;

--
-- Name: usage_events_y2026m10_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.usage_events_pkey ATTACH PARTITION public.usage_events_y2026m10_pkey;

--
-- Name: usage_events_y2026m11_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_occurred_brin ATTACH PARTITION public.usage_events_y2026m11_occurred_at_idx;

--
-- Name: usage_events_y2026m11_organization_id_metric_idempotency_ke_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.uq_usage_events_idempotency ATTACH PARTITION public.usage_events_y2026m11_organization_id_metric_idempotency_ke_idx;

--
-- Name: usage_events_y2026m11_organization_id_metric_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_org_metric_time ATTACH PARTITION public.usage_events_y2026m11_organization_id_metric_occurred_at_idx;

--
-- Name: usage_events_y2026m11_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.usage_events_pkey ATTACH PARTITION public.usage_events_y2026m11_pkey;

--
-- Name: usage_events_y2026m12_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_occurred_brin ATTACH PARTITION public.usage_events_y2026m12_occurred_at_idx;

--
-- Name: usage_events_y2026m12_organization_id_metric_idempotency_ke_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.uq_usage_events_idempotency ATTACH PARTITION public.usage_events_y2026m12_organization_id_metric_idempotency_ke_idx;

--
-- Name: usage_events_y2026m12_organization_id_metric_occurred_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.ix_usage_events_org_metric_time ATTACH PARTITION public.usage_events_y2026m12_organization_id_metric_occurred_at_idx;

--
-- Name: usage_events_y2026m12_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.usage_events_pkey ATTACH PARTITION public.usage_events_y2026m12_pkey;

--
-- Name: agents fk_agents_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT fk_agents_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: api_keys fk_api_keys_created_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT fk_api_keys_created_by_user_id_users FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: api_keys fk_api_keys_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT fk_api_keys_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: audit_logs fk_audit_logs_actor_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_actor_user_id_users FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: audit_logs fk_audit_logs_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT fk_audit_logs_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: billing_customers fk_billing_customers_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.billing_customers
    ADD CONSTRAINT fk_billing_customers_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: entitlements fk_entitlements_created_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entitlements
    ADD CONSTRAINT fk_entitlements_created_by_user_id_users FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: entitlements fk_entitlements_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entitlements
    ADD CONSTRAINT fk_entitlements_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: example_projects fk_example_projects_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.example_projects
    ADD CONSTRAINT fk_example_projects_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: feature_flag_overrides fk_feature_flag_overrides_flag_key_feature_flags; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_flag_overrides
    ADD CONSTRAINT fk_feature_flag_overrides_flag_key_feature_flags FOREIGN KEY (flag_key) REFERENCES public.feature_flags(key) ON DELETE CASCADE;

--
-- Name: feature_flag_overrides fk_feature_flag_overrides_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_flag_overrides
    ADD CONSTRAINT fk_feature_flag_overrides_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: feature_flag_overrides fk_feature_flag_overrides_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_flag_overrides
    ADD CONSTRAINT fk_feature_flag_overrides_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: invoice_lines fk_invoice_lines_invoice_id_invoices; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT fk_invoice_lines_invoice_id_invoices FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE CASCADE;

--
-- Name: invoice_lines fk_invoice_lines_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT fk_invoice_lines_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: invoices fk_invoices_billing_customer_id_billing_customers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoices_billing_customer_id_billing_customers FOREIGN KEY (billing_customer_id) REFERENCES public.billing_customers(id) ON DELETE SET NULL;

--
-- Name: invoices fk_invoices_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT fk_invoices_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: membership_roles fk_membership_roles_membership_id_memberships; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_roles
    ADD CONSTRAINT fk_membership_roles_membership_id_memberships FOREIGN KEY (membership_id) REFERENCES public.memberships(id) ON DELETE CASCADE;

--
-- Name: membership_roles fk_membership_roles_role_id_roles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership_roles
    ADD CONSTRAINT fk_membership_roles_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

--
-- Name: memberships fk_memberships_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT fk_memberships_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: memberships fk_memberships_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memberships
    ADD CONSTRAINT fk_memberships_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: organizations fk_organizations_owner_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT fk_organizations_owner_user_id_users FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: outbox_events fk_outbox_events_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT fk_outbox_events_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: password_reset_tokens fk_password_reset_tokens_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT fk_password_reset_tokens_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: plan_features fk_plan_features_feature_key_features; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_features
    ADD CONSTRAINT fk_plan_features_feature_key_features FOREIGN KEY (feature_key) REFERENCES public.features(key);

--
-- Name: plan_features fk_plan_features_plan_id_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_features
    ADD CONSTRAINT fk_plan_features_plan_id_plans FOREIGN KEY (plan_id) REFERENCES public.plans(id) ON DELETE CASCADE;

--
-- Name: plan_limits fk_plan_limits_metric_metrics; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_limits
    ADD CONSTRAINT fk_plan_limits_metric_metrics FOREIGN KEY (metric) REFERENCES public.metrics(key);

--
-- Name: plan_limits fk_plan_limits_plan_id_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plan_limits
    ADD CONSTRAINT fk_plan_limits_plan_id_plans FOREIGN KEY (plan_id) REFERENCES public.plans(id) ON DELETE CASCADE;

--
-- Name: refresh_tokens fk_refresh_tokens_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT fk_refresh_tokens_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE SET NULL;

--
-- Name: refresh_tokens fk_refresh_tokens_replaced_by_token_id_refresh_tokens; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT fk_refresh_tokens_replaced_by_token_id_refresh_tokens FOREIGN KEY (replaced_by_token_id) REFERENCES public.refresh_tokens(id);

--
-- Name: refresh_tokens fk_refresh_tokens_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT fk_refresh_tokens_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: role_permissions fk_role_permissions_permission_id_permissions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;

--
-- Name: role_permissions fk_role_permissions_role_id_roles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;

--
-- Name: roles fk_roles_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT fk_roles_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: stored_files fk_stored_files_created_by_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_files
    ADD CONSTRAINT fk_stored_files_created_by_user_id_users FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: stored_files fk_stored_files_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_files
    ADD CONSTRAINT fk_stored_files_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: subscriptions fk_subscriptions_billing_customer_id_billing_customers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT fk_subscriptions_billing_customer_id_billing_customers FOREIGN KEY (billing_customer_id) REFERENCES public.billing_customers(id) ON DELETE SET NULL;

--
-- Name: subscriptions fk_subscriptions_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT fk_subscriptions_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: subscriptions fk_subscriptions_plan_id_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT fk_subscriptions_plan_id_plans FOREIGN KEY (plan_id) REFERENCES public.plans(id);

--
-- Name: usage_counters fk_usage_counters_metric_metrics; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_counters
    ADD CONSTRAINT fk_usage_counters_metric_metrics FOREIGN KEY (metric) REFERENCES public.metrics(key);

--
-- Name: usage_counters fk_usage_counters_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_counters
    ADD CONSTRAINT fk_usage_counters_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: usage_idempotency_keys fk_usage_idempotency_keys_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_idempotency_keys
    ADD CONSTRAINT fk_usage_idempotency_keys_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: webhook_deliveries fk_webhook_deliveries_endpoint_id_webhook_endpoints; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT fk_webhook_deliveries_endpoint_id_webhook_endpoints FOREIGN KEY (endpoint_id) REFERENCES public.webhook_endpoints(id) ON DELETE CASCADE;

--
-- Name: webhook_deliveries fk_webhook_deliveries_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT fk_webhook_deliveries_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: webhook_deliveries fk_webhook_deliveries_outbox_event_id_outbox_events; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT fk_webhook_deliveries_outbox_event_id_outbox_events FOREIGN KEY (outbox_event_id) REFERENCES public.outbox_events(id) ON DELETE SET NULL;

--
-- Name: webhook_endpoints fk_webhook_endpoints_organization_id_organizations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_endpoints
    ADD CONSTRAINT fk_webhook_endpoints_organization_id_organizations FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: usage_events usage_events_metric_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.usage_events
    ADD CONSTRAINT usage_events_metric_fkey FOREIGN KEY (metric) REFERENCES public.metrics(key);

--
-- Name: usage_events usage_events_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.usage_events
    ADD CONSTRAINT usage_events_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

--
-- Name: agents; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agents ENABLE ROW LEVEL SECURITY;

--
-- Name: audit_logs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: billing_customers; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.billing_customers ENABLE ROW LEVEL SECURITY;

--
-- Name: entitlements; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.entitlements ENABLE ROW LEVEL SECURITY;

--
-- Name: example_projects; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.example_projects ENABLE ROW LEVEL SECURITY;

--
-- Name: feature_flag_overrides; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.feature_flag_overrides ENABLE ROW LEVEL SECURITY;

--
-- Name: invoice_lines; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.invoice_lines ENABLE ROW LEVEL SECURITY;

--
-- Name: invoices; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;

--
-- Name: memberships; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;

--
-- Name: outbox_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.outbox_events ENABLE ROW LEVEL SECURITY;

--
-- Name: roles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;

--
-- Name: stored_files; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stored_files ENABLE ROW LEVEL SECURITY;

--
-- Name: subscriptions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

--
-- Name: agents tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.agents USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: audit_logs tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.audit_logs USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL)));

--
-- Name: billing_customers tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.billing_customers USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: entitlements tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.entitlements USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: example_projects tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.example_projects USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: feature_flag_overrides tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.feature_flag_overrides USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL) OR (user_id = (NULLIF(current_setting('app.current_user'::text, true), ''::text))::uuid))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL) OR (user_id = (NULLIF(current_setting('app.current_user'::text, true), ''::text))::uuid)));

--
-- Name: invoice_lines tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.invoice_lines USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: invoices tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.invoices USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: memberships tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.memberships USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (user_id = (NULLIF(current_setting('app.current_user'::text, true), ''::text))::uuid))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (user_id = (NULLIF(current_setting('app.current_user'::text, true), ''::text))::uuid)));

--
-- Name: outbox_events tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.outbox_events USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL)));

--
-- Name: roles tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.roles USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text) OR (organization_id IS NULL)));

--
-- Name: stored_files tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.stored_files USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: subscriptions tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.subscriptions USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: usage_counters tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.usage_counters USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: usage_events tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.usage_events USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: usage_idempotency_keys tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.usage_idempotency_keys USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: webhook_deliveries tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.webhook_deliveries USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: webhook_endpoints tenant_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation ON public.webhook_endpoints USING (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text))) WITH CHECK (((organization_id = (NULLIF(current_setting('app.current_tenant'::text, true), ''::text))::uuid) OR (current_setting('app.rls_platform'::text, true) = 'on'::text)));

--
-- Name: usage_counters; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.usage_counters ENABLE ROW LEVEL SECURITY;

--
-- Name: usage_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;

--
-- Name: usage_idempotency_keys; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.usage_idempotency_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: webhook_deliveries; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.webhook_deliveries ENABLE ROW LEVEL SECURITY;

--
-- Name: webhook_endpoints; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.webhook_endpoints ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--
