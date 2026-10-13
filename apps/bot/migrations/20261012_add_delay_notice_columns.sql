ALTER TABLE coach_ai_jobs
    ADD COLUMN IF NOT EXISTS delay_notified_at timestamptz,
    ADD COLUMN IF NOT EXISTS delay_notice_claimed_at timestamptz,
    ADD COLUMN IF NOT EXISTS delay_notice_claim_token text,
    ADD COLUMN IF NOT EXISTS delay_notice_attempts integer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'coach_ai_jobs'::regclass
          AND conname = 'coach_ai_jobs_delay_notice_attempts_nonnegative'
    ) THEN
        ALTER TABLE coach_ai_jobs
            ADD CONSTRAINT coach_ai_jobs_delay_notice_attempts_nonnegative
            CHECK (delay_notice_attempts IS NULL OR delay_notice_attempts >= 0);
    END IF;
END
$$;
