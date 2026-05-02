-- Run this in the Supabase SQL Editor to create the table and index

create table if not exists food_analyses (
    id              uuid primary key default gen_random_uuid(),
    image_hash      text        not null,
    food_name       text        not null,
    estimated_calories integer  not null,
    protein_g       numeric(6, 2) not null,
    carbs_g         numeric(6, 2) not null,
    fat_g           numeric(6, 2) not null,
    fiber_g         numeric(6, 2) not null,
    model_used      text        not null,
    confidence      text        not null check (confidence in ('high', 'medium', 'low')),
    tier            text        not null check (tier in ('Basic', 'Pro')),
    analyzed_date   date        not null,
    created_at      timestamptz not null default now()
);

-- Speeds up the daily cache lookup (image_hash + date)
create index if not exists idx_food_analyses_hash_date
    on food_analyses (image_hash, analyzed_date);

-- ── Users (VIP flag) ──────────────────────────────────────────────────────────

create table if not exists users (
    id                  uuid primary key default gen_random_uuid(),
    email               text unique not null,
    is_vip              boolean not null default false,
    stripe_customer_id  text,
    created_at          timestamptz not null default now()
);

-- Optional: auto-delete rows older than 30 days to keep the table lean
-- (Requires pg_cron extension enabled in Supabase Dashboard → Extensions)
-- select cron.schedule(
--   'delete-old-analyses',
--   '0 3 * * *',
--   $$ delete from food_analyses where analyzed_date < current_date - interval '30 days' $$
-- );
