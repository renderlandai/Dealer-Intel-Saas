-- Single RPC that returns match statistics scoped to an organization.
-- Replaces fetching all match rows + counting in Python.
CREATE OR REPLACE FUNCTION get_match_stats_for_org(p_org_id UUID)
RETURNS JSON
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_total         INT;
    v_compliant     INT;
    v_violations    INT;
    v_pending       INT;
    v_exact         INT;
    v_strong        INT;
    v_partial       INT;
    v_avg_conf      NUMERIC;
BEGIN
    SELECT
        count(*),
        count(*) FILTER (WHERE compliance_status = 'compliant'),
        count(*) FILTER (WHERE compliance_status = 'violation'),
        count(*) FILTER (WHERE compliance_status = 'pending'),
        count(*) FILTER (WHERE match_type = 'exact'),
        count(*) FILTER (WHERE match_type = 'strong'),
        count(*) FILTER (WHERE match_type = 'partial'),
        COALESCE(ROUND(AVG(confidence_score)::numeric, 2), 0)
    INTO v_total, v_compliant, v_violations, v_pending,
         v_exact, v_strong, v_partial, v_avg_conf
    FROM matches m
    WHERE m.distributor_id IN (
        SELECT id FROM distributors WHERE organization_id = p_org_id
    )
    OR m.asset_id IN (
        SELECT a.id FROM assets a
        JOIN campaigns c ON a.campaign_id = c.id
        WHERE c.organization_id = p_org_id
    );

    RETURN json_build_object(
        'total_matches',      v_total,
        'compliant',          v_compliant,
        'violations',         v_violations,
        'pending_review',     v_pending,
        'by_type',            json_build_object(
            'exact',  v_exact,
            'strong', v_strong,
            'partial', v_partial
        ),
        'average_confidence', v_avg_conf,
        'compliance_rate',    CASE WHEN v_total > 0
            THEN ROUND((v_compliant::numeric / v_total) * 100, 1)
            ELSE 0 END
    );
END;
$$;
