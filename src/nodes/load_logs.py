import os
import sqlite3
from dotenv import load_dotenv
from src.schemas.state import LogMonState

load_dotenv()

DB_PATH = os.getenv('SQLITE_DB_PATH')


def load_logs(state: LogMonState) -> LogMonState:
    """SQLite에서 최신 로그 조회"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute('''
        SELECT timestamp, host, auth_type, auth_result, auth_reason,
               user_id, status_code, co_cl_cd
        FROM log_swg_lib
        ORDER BY timestamp DESC
        LIMIT 500
    ''')
    swg_lib_logs = [dict(r) for r in cur.fetchall()]

    cur.execute('''
        SELECT timestamp, host, log_level, logger, log_message
        FROM log_catalina
        ORDER BY timestamp DESC
        LIMIT 500
    ''')
    catalina_logs = [dict(r) for r in cur.fetchall()]

    cur.execute('''
        SELECT timestamp, host, response_time, throughput,
               busy_threads, max_threads, current_connections,
               exceeded_limit, core_result
        FROM log_smps_stats
        ORDER BY timestamp DESC
        LIMIT 500
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
