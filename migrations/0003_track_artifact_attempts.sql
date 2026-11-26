-- Track which execution attempt produced each artifact.
-- Existing artifact rows are assigned to their job's current attempt so that
-- deploying this migration does not hide already completed historical results.

ALTER TABLE music_job_artifacts
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER;

UPDATE music_job_artifacts AS a
SET attempt_count = COALESCE(j.attempt_count, 0)
FROM music_jobs AS j
WHERE j.id = a.job_id
  AND a.attempt_count IS NULL;

ALTER TABLE music_job_artifacts
    ALTER COLUMN attempt_count SET DEFAULT 0;

ALTER TABLE music_job_artifacts
    ALTER COLUMN attempt_count SET NOT NULL;

CREATE INDEX IF NOT EXISTS music_job_artifacts_attempt_idx
    ON music_job_artifacts (job_id, attempt_count, id);
