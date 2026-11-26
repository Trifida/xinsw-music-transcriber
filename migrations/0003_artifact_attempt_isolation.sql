-- Associate every artifact with the worker attempt that produced it.
-- A retry increments music_jobs.attempt_count; artifacts from earlier attempts
-- remain stored for audit but are no longer exposed as current task results.

ALTER TABLE music_job_artifacts
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER;

UPDATE music_job_artifacts AS a
SET attempt_count = COALESCE(j.attempt_count, 1)
FROM music_jobs AS j
WHERE j.id = a.job_id
  AND a.attempt_count IS NULL;

UPDATE music_job_artifacts
SET attempt_count = 1
WHERE attempt_count IS NULL;

ALTER TABLE music_job_artifacts
    ALTER COLUMN attempt_count SET DEFAULT 1,
    ALTER COLUMN attempt_count SET NOT NULL;
