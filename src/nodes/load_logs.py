import os
import sqlite3
from dotenv import load_dotenv
from src.schemas.state import LogMonState

load_dotenv()
DB_PATH = os.getenv('SQLITE_DB_PATH')


def load_logs(state: LogMonState) -> LogMonState:
    """SQLite에서 로그 조회.
    state에 target_time(UTC ISO8601)이 있으면 해당 시점 기준 ±10분 조회.
    없으면 최신 500건 조회.
    """
    target_time = state.get('target_time')  # 예: "2026-06-28T00:00:00.000Z"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if target_time:
        time_filter = f"""
            WHERE timestamp >= datetime('{target_time}', '-10 minutes')
            AND   timestamp <= datetime('{target_time}', '+10 minutes')
        """
        order_limit = "ORDER BY timestamp DESC"
        print(f'  [load_logs] target_time: {target_time} (±10분)')
    else:
        time_filter = ""
        order_limit = "ORDER BY timestamp DESC LIMIT 500"

    cur.execute(f'''
        SELECT timestamp, host, auth_type, auth_result, auth_reason,
               user_id, status_code, co_cl_cd
        FROM log_swg_lib
        {time_filter}
        {order_limit}
    ''')
    swg_lib_logs = [dict(r) for r in cur.fetchall()]

    cur.execute(f'''
        SELECT timestamp, host, log_level, logger, log_message
        FROM log_catalina
        {time_filter}
        {order_limit}
    ''')
    catalina_logs = [dict(r) for r in cur.fetchall()]

    cur.execute(f'''
        SELECT timestamp, host, response_time, throughput,
               busy_threads, max_threads, current_connections,
               exceeded_limit, core_result
        FROM log_smps_stats
        {time_filter}
        {order_limit}
    ''')
    smps_stats_logs = [dict(r) for r in cur.fetchall()]

    conn.close()
    print(f'  swg_lib   : {len(swg_lib_logs)}건')
    print(f'  catalina  : {len(catalina_logs)}건')
    print(f'  smps_stats: {len(smps_stats_logs)}건')

    return {
        **state,
        'swg_lib_logs': swg_lib_logs,
        'catalina_logs': catalina_logs,
        'smps_stats_logs': smps_stats_logs,
    }