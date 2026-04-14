-- Single RPC that returns all dashboard stats in one round-trip.
-- Replaces 8+ sequential queries from the API server.
CREATE OR REPLACE FUNCTION get_dashboard_stats(p_org_id UUID)
RETURNS JSON
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_active_campaigns   INT;
    v_total_assets       INT;
    v_active_distributors INT;
    v_total_matches      INT;
    v_compliant_count    INT;
    v_violations_count   INT;
    v_matches_today      INT;
    v_unread_alerts      INT;
    v_compliance_rate    NUMERIC;
BEGIN
    SELECT count(*) INTO v_active_campaigns
    FROM campaigns
    WHERE organization_id = p_org_id AND status = 'active';

    SELECT count(*) INTO v_total_assets
    FROM assets a
    JOIN campaigns c ON a.campaign_id = c.id
    WHERE c.organization_id = p_org_id;

    SELECT count(*) INTO v_active_distributors
    FROM distributors
    WHERE organization_id = p_org_id AND status = 'active';

    SELECT
        count(*),
        count(*) FILTER (WHERE compliance_status = 'compliant'),
        count(*) FILTER (WHERE compliance_status = 'violation'),
        count(*) FILTER (WHERE m.created_at::date = CURRENT_DATE)
    INTO v_total_matches, v_compliant_count, v_violations_count, v_matches_today
    FROM matches m
    WHERE m.distributor_id IN (
        SELECT id FROM distributors WHERE organization_id = p_org_id
    )
    OR m.asset_id IN (
        SELECT a.id FROM assets a
        JOIN campaigns c ON a.campaign_id = c.id
        WHERE c.organization_id = p_org_id
    );

    SELECT count(*) INTO v_unread_alerts
    FROM alerts
    WHERE organization_id = p_org_id AND is_read = FALSE;

    IF v_total_matches > 0 THEN
        v_compliance_rate := ROUND((v_compliant_count::NUMERIC / v_total_matches) * 100, 1);
    ELSE
        v_compliance_rate := 0;
    END IF;

    RETURN json_build_object(
        'active_campaigns',   v_active_campaigns,
        'total_assets',       v_total_assets,
        'active_distributors', v_active_distributors,
        'total_matches',      v_total_matches,
        'compliant_count',    v_compliant_count,
        'violations_count',   v_violations_count,
        'matches_today',      v_matches_today,
        'unread_alerts',      v_unread_alerts,
        'compliance_rate',    v_compliance_rate
    );
END;
$$;
