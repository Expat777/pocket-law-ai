-- Схема 3.4 из TEAM_PLAN.md

CREATE TABLE IF NOT EXISTS users (
    user_id     BIGINT PRIMARY KEY,
    tg_username TEXT,
    consent_at  TIMESTAMPTZ,  -- согласие на обработку ПДн (152-ФЗ); NULL = согласия ещё нет, бот не отвечает
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dialog_history (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id),
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    citations  JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS law_versions (
    id            BIGSERIAL PRIMARY KEY,
    act           TEXT NOT NULL,
    article_no    TEXT NOT NULL,
    revision_date DATE NOT NULL,
    hash          TEXT NOT NULL,
    status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confidence_log (
    id         BIGSERIAL PRIMARY KEY,
    question   TEXT NOT NULL,
    answer_id  BIGINT,
    confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dialog_history_user_id ON dialog_history(user_id);
CREATE INDEX IF NOT EXISTS idx_law_versions_act_article ON law_versions(act, article_no);
