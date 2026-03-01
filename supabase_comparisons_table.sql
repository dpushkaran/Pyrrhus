CREATE TABLE comparisons (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    comparison_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Task metadata
    task TEXT NOT NULL,
    category TEXT,
    prompt_id BIGINT,
    budget DOUBLE PRECISION NOT NULL,
    mode TEXT DEFAULT 'capped',

    -- Pipeline structure
    num_subtasks INT,
    num_skipped INT,
    tier_fast INT DEFAULT 0,
    tier_verify INT DEFAULT 0,
    tier_deep INT DEFAULT 0,
    planner_cost DOUBLE PRECISION,

    -- Cost comparison
    pyrrhus_cost DOUBLE PRECISION,
    baseline_cost DOUBLE PRECISION,
    cost_savings_pct DOUBLE PRECISION,

    -- Quality scores (Pyrrhus)
    pyrrhus_quality DOUBLE PRECISION,
    pyrrhus_relevance DOUBLE PRECISION,
    pyrrhus_completeness DOUBLE PRECISION,
    pyrrhus_coherence DOUBLE PRECISION,
    pyrrhus_conciseness DOUBLE PRECISION,

    -- Quality scores (Baseline)
    baseline_quality DOUBLE PRECISION,
    baseline_relevance DOUBLE PRECISION,
    baseline_completeness DOUBLE PRECISION,
    baseline_coherence DOUBLE PRECISION,
    baseline_conciseness DOUBLE PRECISION,
    quality_delta DOUBLE PRECISION,

    -- Text metrics (Pyrrhus)
    pyrrhus_word_count INT,
    pyrrhus_ttr DOUBLE PRECISION,
    pyrrhus_compression DOUBLE PRECISION,
    pyrrhus_ngram_rep DOUBLE PRECISION,
    pyrrhus_avg_sent_len DOUBLE PRECISION,
    pyrrhus_fillers INT,

    -- Text metrics (Baseline)
    baseline_word_count INT,
    baseline_ttr DOUBLE PRECISION,
    baseline_compression DOUBLE PRECISION,
    baseline_ngram_rep DOUBLE PRECISION,
    baseline_avg_sent_len DOUBLE PRECISION,
    baseline_fillers INT
);

CREATE INDEX idx_comparisons_category ON comparisons(category);
CREATE INDEX idx_comparisons_budget ON comparisons(budget);
CREATE INDEX idx_comparisons_created ON comparisons(created_at);
