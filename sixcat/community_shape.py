"""Strict nested allowlists for public receipts (no executable validation)."""
from .community import object_keys, require
from .score import CATEGORIES

STATS = ('score n truncated trunc_in_think empty_answer loop_failures parse_high_confidence '
         'parse_low_confidence parse_confidence_not_applicable parse_confidence_missing ctok_p50 '
         'ctok_p95 ctok_max rtok_sum atok_sum rtok_p50 atok_p50 speed_n prefill_tps_p50 '
         'prefill_tps_p95 decode_tps_p50 decode_tps_p95 tps_n tps_mean total_ctok total_wall_s suite_tps').split()
POLICY = 'name temperature top_p top_k min_p thinking budgets extra source'.split()
PARAMS = ('temperature max_tokens max_completion_tokens top_p top_k min_p seed presence_penalty '
          'frequency_penalty repetition_penalty stop reasoning_effort enable_thinking preclose_think').split()


def validate_nested(result):
    object_keys(result['policy'], POLICY, required=POLICY)
    object_keys(result['policy']['extra'], PARAMS)
    for v in result['policy']['extra'].values():
        require(v is None or type(v) in (str, int, float, bool) or
                (isinstance(v, list) and all(isinstance(x, str) for x in v)), 'Invalid policy extra value')
    object_keys(result['policy']['budgets'], CATEGORIES, required=CATEGORIES)
    object_keys(result['budgets'], CATEGORIES, required=CATEGORIES)
    object_keys(result['overall'], ['policy', 'score'], required=['policy', 'score'])
    for key in ('n', 'expected_n', 'categories', 'stats', 'items'):
        object_keys(result[key], CATEGORIES, required=CATEGORIES)
    for stats in result['stats'].values():
        object_keys(stats, STATS)
        require(all(v is None or type(v) in (int, float) for v in stats.values()), 'Invalid statistics value')
    require(isinstance(result['overall_flags'], list) and all(isinstance(s, str) for s in result['overall_flags']), 'Invalid flags')
    for rows in result['items'].values():
        for row in rows:
            for key, value in row.items():
                if key in ('request_params', 'tool_calls'):
                    continue
                require(value is None or type(value) in (str, bool, int, float), 'Unexpected nested item metadata')
            params = row.get('request_params')
            require(isinstance(params, dict), 'Missing request settings')
            object_keys(params, PARAMS)
            for value in params.values():
                require(value is None or type(value) in (str, int, float, bool) or
                        (isinstance(value, list) and all(isinstance(x, str) for x in value)), 'Invalid request parameter')
            calls = row.get('tool_calls')
            if calls is not None:
                require(isinstance(calls, list) and len(calls) <= 128, 'Invalid tool call list')
                for call in calls:
                    object_keys(call, ['id', 'type', 'function'], required=['function'])
                    object_keys(call['function'], ['name', 'arguments'], required=['name', 'arguments'])
                    require(all(isinstance(v, str) for v in call['function'].values()), 'Tool calls must preserve string arguments')
                    require(all(isinstance(v, str) for k, v in call.items() if k != 'function'), 'Invalid tool call metadata')
    for segment in result['execution_segments']:
        require(all(v is None or type(v) in (str, int, float, bool) for v in segment.values()), 'Invalid execution telemetry')
