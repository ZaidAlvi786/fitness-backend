-- ============================================================================================
-- Momentum — initial schema: profiles, sessions, step_records (+ a daily aggregate view).
--
-- Shared Postgres owned by Supabase. The Android client does direct, RLS-scoped CRUD with the
-- user's anon-key + JWT; the FastAPI backend reads aggregates with the same user JWT. EVERY row is
-- scoped to auth.uid() via RLS — the service-role key (which bypasses RLS) exists only in the
-- backend, never on the client.
--
-- Columns are snake_case (Postgres idiom); the Android sync layer maps them to the camelCase Room
-- entities. Tables mirror StepRecordEntity / SessionEntity / UserProfile and re-assert the same
-- domain invariants as CHECK constraints so the database rejects bad rows even if a client doesn't.
-- ============================================================================================

-- ---- helper: keep updated_at fresh on UPDATE ----
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

-- ========================================= profiles =========================================
-- One row per user, keyed by the Supabase user id. The client upserts this during profile setup
-- (gender/goal are captured then), so there is no auto-create trigger.
create table if not exists public.profiles (
    id           uuid primary key references auth.users (id) on delete cascade,
    display_name text not null check (char_length(display_name) between 1 and 80),
    gender       text not null check (gender in ('MALE', 'FEMALE', 'OTHER')),
    weight_kg    integer check (weight_kg between 20 and 400),
    height_cm    integer check (height_cm between 50 and 260),
    goal         text not null check (goal in ('BUILD_MUSCLE', 'LOSE_WEIGHT', 'IMPROVE_ENDURANCE', 'STAY_ACTIVE')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create trigger profiles_set_updated_at
    before update on public.profiles
    for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;

create policy "profiles_select_own" on public.profiles
    for select using (auth.uid() = id);
create policy "profiles_insert_own" on public.profiles
    for insert with check (auth.uid() = id);
create policy "profiles_update_own" on public.profiles
    for update using (auth.uid() = id) with check (auth.uid() = id);
create policy "profiles_delete_own" on public.profiles
    for delete using (auth.uid() = id);

-- ========================================= sessions =========================================
-- Mirrors SessionEntity. id is the client-generated string id (text, not uuid, to accept whatever
-- IdGenerator emits). user_id defaults to auth.uid() so the client need not send it; RLS still
-- enforces it. The state/end + type_kind invariants match the domain mapper.
create table if not exists public.sessions (
    id                 text primary key,
    user_id            uuid not null default auth.uid() references auth.users (id) on delete cascade,
    type_kind          text not null check (type_kind in ('DETECTED', 'SPORT')),
    detected_type      text,
    sport_kind         text,
    state              text not null check (state in ('ACTIVE', 'COMPLETED')),
    start_millis       bigint not null,
    end_millis         bigint,
    epoch_day          bigint not null,
    steps              bigint not null default 0 check (steps >= 0),
    distance_meters    double precision not null default 0 check (distance_meters >= 0),
    calories_kcal      double precision not null default 0 check (calories_kcal >= 0),
    avg_heart_rate     integer check (avg_heart_rate between 0 and 300),
    peak_heart_rate    integer check (peak_heart_rate between 0 and 300),
    live_detected_type text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    constraint sessions_end_after_start check (end_millis is null or end_millis >= start_millis),
    constraint sessions_state_end check (
        (state = 'ACTIVE' and end_millis is null) or
        (state = 'COMPLETED' and end_millis is not null)
    ),
    constraint sessions_type_kind_fields check (
        (type_kind = 'DETECTED' and detected_type is not null) or
        (type_kind = 'SPORT' and sport_kind is not null)
    )
);

create index if not exists sessions_user_idx on public.sessions (user_id);
create index if not exists sessions_user_epoch_idx on public.sessions (user_id, epoch_day);
create index if not exists sessions_user_start_idx on public.sessions (user_id, start_millis desc);
create index if not exists sessions_user_state_idx on public.sessions (user_id, state);

create trigger sessions_set_updated_at
    before update on public.sessions
    for each row execute function public.set_updated_at();

alter table public.sessions enable row level security;

create policy "sessions_select_own" on public.sessions
    for select using (auth.uid() = user_id);
create policy "sessions_insert_own" on public.sessions
    for insert with check (auth.uid() = user_id);
create policy "sessions_update_own" on public.sessions
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "sessions_delete_own" on public.sessions
    for delete using (auth.uid() = user_id);

-- ======================================= step_records =======================================
-- Mirrors StepRecordEntity — the raw step deltas. High write volume: the client batches these into
-- bulk upserts on a WorkManager cadence (never per-sample). id is the client-generated string id.
create table if not exists public.step_records (
    id           text primary key,
    user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
    steps        bigint not null check (steps >= 0),
    start_millis bigint not null,
    end_millis   bigint not null,
    epoch_day    bigint not null,
    source       text not null,
    boot_id      bigint not null,
    created_at   timestamptz not null default now(),
    constraint step_records_end_after_start check (end_millis >= start_millis)
);

create index if not exists step_records_user_epoch_idx on public.step_records (user_id, epoch_day);
create index if not exists step_records_user_end_idx on public.step_records (user_id, end_millis);

alter table public.step_records enable row level security;

create policy "step_records_select_own" on public.step_records
    for select using (auth.uid() = user_id);
create policy "step_records_insert_own" on public.step_records
    for insert with check (auth.uid() = user_id);
create policy "step_records_update_own" on public.step_records
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "step_records_delete_own" on public.step_records
    for delete using (auth.uid() = user_id);

-- ==================================== daily_activity view ====================================
-- security_invoker = true → the view evaluates under the CALLER's RLS, so each user only ever
-- aggregates their own step_records. This is the read seam the FastAPI aggregation endpoint uses
-- (with the user's JWT) — heavy roll-ups stay in Postgres instead of shipping raw rows to clients.
create or replace view public.daily_activity
    with (security_invoker = true) as
select
    user_id,
    epoch_day,
    sum(steps)::bigint as total_steps,
    count(*)::int      as record_count,
    min(start_millis)  as first_millis,
    max(end_millis)    as last_millis
from public.step_records
group by user_id, epoch_day;
