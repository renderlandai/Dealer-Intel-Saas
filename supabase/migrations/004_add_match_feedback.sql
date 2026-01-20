-- Migration: Add match feedback table for continuous learning
-- This enables tracking of match accuracy to improve AI calibration over time

-- Create match_feedback table
CREATE TABLE IF NOT EXISTS match_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id UUID REFERENCES matches(id) ON DELETE CASCADE,
    
    -- Feedback data
    was_correct BOOLEAN NOT NULL,
    actual_verdict VARCHAR(50) NOT NULL,  -- 'true_positive', 'false_positive', 'true_negative', 'false_negative'
    
    -- Context for learning
    ai_confidence FLOAT,                   -- Original AI confidence score
    source_type VARCHAR(50),               -- page_screenshot, website_banner, ad, etc.
    channel VARCHAR(50),                   -- google_ads, facebook, website, etc.
    match_type VARCHAR(20),                -- exact, strong, partial, weak
    
    -- Reviewer info
    reviewed_by UUID,
    review_notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index for efficient queries
CREATE INDEX IF NOT EXISTS idx_match_feedback_created_at ON match_feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_match_feedback_source_type ON match_feedback(source_type);
CREATE INDEX IF NOT EXISTS idx_match_feedback_channel ON match_feedback(channel);
CREATE INDEX IF NOT EXISTS idx_match_feedback_was_correct ON match_feedback(was_correct);

-- Create view for accuracy statistics
CREATE OR REPLACE VIEW feedback_accuracy_stats AS
SELECT 
    source_type,
    channel,
    match_type,
    COUNT(*) as total_reviews,
    COUNT(*) FILTER (WHERE was_correct = true) as correct_count,
    COUNT(*) FILTER (WHERE was_correct = false) as incorrect_count,
    ROUND(
        (COUNT(*) FILTER (WHERE was_correct = true)::NUMERIC / NULLIF(COUNT(*), 0) * 100),
        2
    ) as accuracy_percentage,
    AVG(ai_confidence) as avg_confidence,
    AVG(ai_confidence) FILTER (WHERE was_correct = true) as avg_confidence_correct,
    AVG(ai_confidence) FILTER (WHERE was_correct = false) as avg_confidence_incorrect
FROM match_feedback
GROUP BY source_type, channel, match_type;

-- Create function to calculate optimal threshold for a source/channel combination
CREATE OR REPLACE FUNCTION calculate_optimal_threshold(
    p_source_type VARCHAR,
    p_channel VARCHAR,
    p_min_samples INT DEFAULT 20
)
RETURNS TABLE (
    recommended_threshold INT,
    sample_count INT,
    false_positive_rate NUMERIC,
    false_negative_rate NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    WITH feedback_data AS (
        SELECT 
            ai_confidence,
            was_correct,
            actual_verdict
        FROM match_feedback
        WHERE source_type = p_source_type 
          AND channel = p_channel
    ),
    sample_count AS (
        SELECT COUNT(*) as cnt FROM feedback_data
    )
    SELECT 
        CASE 
            WHEN (SELECT cnt FROM sample_count) < p_min_samples THEN 40  -- Default
            ELSE ROUND(
                AVG(CASE WHEN was_correct THEN ai_confidence ELSE NULL END) -
                STDDEV(CASE WHEN was_correct THEN ai_confidence ELSE NULL END) * 0.5
            )::INT
        END as recommended_threshold,
        (SELECT cnt FROM sample_count)::INT as sample_count,
        ROUND(
            (COUNT(*) FILTER (WHERE actual_verdict = 'false_positive')::NUMERIC / 
             NULLIF(COUNT(*), 0) * 100), 2
        ) as false_positive_rate,
        ROUND(
            (COUNT(*) FILTER (WHERE actual_verdict = 'false_negative')::NUMERIC / 
             NULLIF(COUNT(*), 0) * 100), 2
        ) as false_negative_rate
    FROM feedback_data;
END;
$$ LANGUAGE plpgsql;

-- Add columns to matches table for tracking review status
ALTER TABLE matches 
ADD COLUMN IF NOT EXISTS feedback_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS feedback_id UUID REFERENCES match_feedback(id);

-- Create index for pending reviews
CREATE INDEX IF NOT EXISTS idx_matches_feedback_status ON matches(feedback_status);

COMMENT ON TABLE match_feedback IS 'Stores user feedback on match accuracy for continuous AI improvement';
COMMENT ON COLUMN match_feedback.actual_verdict IS 'true_positive = correctly matched, false_positive = incorrectly matched, false_negative = missed match';








