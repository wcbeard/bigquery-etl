-- Query generated by:
-- templates/clients_daily_scalar_aggregates.sql.py --agg-type keyed_scalars
WITH filtered AS (
    SELECT
        *,
        SPLIT(application.version, '.')[OFFSET(0)] AS app_version,
        DATE(submission_timestamp) as submission_date,
        normalized_os as os,
        application.build_id AS app_build_id,
        normalized_channel AS channel
    FROM `moz-fx-data-shared-prod.telemetry_stable.main_v4`
    WHERE DATE(submission_timestamp) = @submission_date
        AND normalized_channel in (
          "release", "beta", "nightly"
        )
        AND client_id IS NOT NULL),

grouped_metrics AS
  (SELECT
    client_id,
    submission_date,
    os,
    app_version,
    app_build_id,
    channel,
    ARRAY<STRUCT<
        name STRING,
        value ARRAY<STRUCT<key STRING, value INT64>>
    >>[
        ('browser_engagement_navigation_about_home', payload.processes.parent.keyed_scalars.browser_engagement_navigation_about_home),
        ('networking_data_transferred_kb', payload.processes.parent.keyed_scalars.networking_data_transferred_kb),
        ('browser_errors_collected_count_by_filename', payload.processes.parent.keyed_scalars.browser_errors_collected_count_by_filename),
        ('update_bitshresult', payload.processes.parent.keyed_scalars.update_bitshresult),
        ('security_webauthn_used', payload.processes.parent.keyed_scalars.security_webauthn_used),
        ('devtools_current_theme', payload.processes.parent.keyed_scalars.devtools_current_theme),
        ('browser_engagement_navigation_about_newtab', payload.processes.parent.keyed_scalars.browser_engagement_navigation_about_newtab),
        ('browser_engagement_navigation_contextmenu', payload.processes.parent.keyed_scalars.browser_engagement_navigation_contextmenu),
        ('update_binarytransparencyresult', payload.processes.parent.keyed_scalars.update_binarytransparencyresult),
        ('browser_engagement_navigation_searchbar', payload.processes.parent.keyed_scalars.browser_engagement_navigation_searchbar),
        ('browser_engagement_navigation_webextension', payload.processes.parent.keyed_scalars.browser_engagement_navigation_webextension),
        ('devtools_accessibility_simulation_activated', payload.processes.parent.keyed_scalars.devtools_accessibility_simulation_activated),
        ('devtools_accessibility_select_accessible_for_node', payload.processes.parent.keyed_scalars.devtools_accessibility_select_accessible_for_node),
        ('devtools_responsive_open_trigger', payload.processes.parent.keyed_scalars.devtools_responsive_open_trigger),
        ('preferences_search_query', payload.processes.parent.keyed_scalars.preferences_search_query),
        ('resistfingerprinting_content_window_size', payload.processes.parent.keyed_scalars.resistfingerprinting_content_window_size),
        ('devtools_toolbox_tabs_reordered', payload.processes.parent.keyed_scalars.devtools_toolbox_tabs_reordered),
        ('security_client_cert', payload.processes.parent.keyed_scalars.security_client_cert),
        ('pictureinpicture_closed_method', payload.processes.parent.keyed_scalars.pictureinpicture_closed_method),
        ('qm_origin_directory_unexpected_filename', payload.processes.parent.keyed_scalars.qm_origin_directory_unexpected_filename),
        ('browser_engagement_navigation_urlbar', payload.processes.parent.keyed_scalars.browser_engagement_navigation_urlbar),
        ('gfx_advanced_layers_failure_id', payload.processes.parent.keyed_scalars.gfx_advanced_layers_failure_id),
        ('preferences_use_current_page', payload.processes.parent.keyed_scalars.preferences_use_current_page),
        ('images_webp_content_frequency', payload.processes.parent.keyed_scalars.images_webp_content_frequency),
        ('extensions_updates_rdf', payload.processes.parent.keyed_scalars.extensions_updates_rdf),
        ('networking_data_transferred_v3_kb', payload.processes.parent.keyed_scalars.networking_data_transferred_v3_kb),
        ('normandy_recipe_freshness', payload.processes.parent.keyed_scalars.normandy_recipe_freshness),
        ('devtools_tooltip_shown', payload.processes.parent.keyed_scalars.devtools_tooltip_shown),
        ('devtools_accessibility_accessible_context_menu_item_activated', payload.processes.parent.keyed_scalars.devtools_accessibility_accessible_context_menu_item_activated),
        ('telemetry_keyed_scalars_exceed_limit', payload.processes.parent.keyed_scalars.telemetry_keyed_scalars_exceed_limit),
        ('browser_search_ad_clicks', payload.processes.parent.keyed_scalars.browser_search_ad_clicks),
        ('storage_sync_api_usage_storage_consumed', payload.processes.parent.keyed_scalars.storage_sync_api_usage_storage_consumed),
        ('preferences_browser_home_page_count', payload.processes.parent.keyed_scalars.preferences_browser_home_page_count),
        ('preferences_use_bookmark', payload.processes.parent.keyed_scalars.preferences_use_bookmark),
        ('storage_sync_api_usage_items_stored', payload.processes.parent.keyed_scalars.storage_sync_api_usage_items_stored),
        ('browser_search_with_ads', payload.processes.parent.keyed_scalars.browser_search_with_ads),
        ('preferences_browser_home_page_change', payload.processes.parent.keyed_scalars.preferences_browser_home_page_change),
        ('telemetry_accumulate_clamped_values', payload.processes.parent.keyed_scalars.telemetry_accumulate_clamped_values),
        ('devtools_accessibility_audit_activated', payload.processes.parent.keyed_scalars.devtools_accessibility_audit_activated),
        ('devtools_inspector_three_pane_enabled', payload.processes.parent.keyed_scalars.devtools_inspector_three_pane_enabled)
    ] as metrics
  FROM filtered),

flattened_metrics AS
  (SELECT
    client_id,
    submission_date,
    os,
    app_version,
    app_build_id,
    channel,
    metrics.name AS metric,
    value.key AS key,
    value.value AS value
  FROM grouped_metrics
  CROSS JOIN unnest(metrics) AS metrics,
  unnest(metrics.value) AS value),

aggregated AS (
    SELECT
        submission_date,
        client_id,
        os,
        app_version,
        app_build_id,
        channel,
        metric,
        key,
        MAX(value) AS max,
        MIN(value) AS min,
        AVG(value) AS avg,
        SUM(value) AS sum,
        COUNT(*) AS count
    FROM flattened_metrics
    GROUP BY
        submission_date,
        client_id,
        os,
        app_version,
        app_build_id,
        channel,
        metric,
        key)

SELECT
    client_id,
    submission_date,
    os,
    app_version,
    app_build_id,
    channel,
    ARRAY_CONCAT_AGG(ARRAY<STRUCT<
        metric STRING,
        metric_type STRING,
        key STRING,
        agg_type STRING,
        value FLOAT64
    >>
        [
            (metric, 'keyed-scalar', key, 'max', max),
            (metric, 'keyed-scalar', key, 'min', min),
            (metric, 'keyed-scalar', key, 'avg', avg),
            (metric, 'keyed-scalar', key, 'sum', sum),
            (metric, 'keyed-scalar', key, 'count', count)
        ]
) AS scalar_aggregates
FROM aggregated
GROUP BY
    client_id,
    submission_date,
    os,
    app_version,
    app_build_id,
    channel
