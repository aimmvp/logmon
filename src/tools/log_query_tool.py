"""
log_query_tool
- SQLite에서 지정된 host/time_range 조건으로 로그 조회
- compare_baseline=True 시 전주 동일 시점 데이터 함께 반환
"""

import os
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("SQLITE_DB_PATH")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _query_swg_lib(
    cur: sqlite3.Cursor,
    host: str | None,
    start: str,
    end: str,
    limit: int = 500,
) -> list[dict]:
    where = "WHERE timestamp >= ? AND timestamp <= ?"
    params = [start, end]
    if host:
        where += " AND host = ?"
        params.append(host)

    cur.execute(f"""
        SELECT timestamp, host, auth_type, auth_result, auth_reason,
               user_id, co_cl_cd
        FROM log_swg_lib
        {where}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """, params)
    return [dict(r) for r in cur.fetchall()]


def _query_catalina(
    cur: sqlite3.Cursor,
    host: str | None,
    start: str,
    end: str,
    limit: int = 500,
) -> list[dict]:
    where = "WHERE timestamp >= ? AND timestamp <= ?"
    params = [start, end]
    if host:
        where += " AND host = ?"
        params.append(host)

    cur.execute(f"""
        SELECT timestamp, host, log_level, logger, log_message
        FROM log_catalina
        {where}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """, params)
    return [dict(r) for r in cur.fetchall()]


def _query_smps_stats(
    cur: sqlite3.Cursor,
    host: str | None,
    start: str,
    end: str,
    limit: int = 200,
) -> list[dict]:
    where = "WHERE timestamp >= ? AND timestamp <= ?"
    params = [start, end]
    if host:
        where += " AND host = ?"
        params.append(host)

    cur.execute(f"""
        SELECT timestamp, host, response_time, busy_threads,
               throughput, exceeded_limit, core_result,
               current_connections, max_connections
        FROM log_smps_stats
        {where}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """, params)
    return [dict(r) for r in cur.fetchall()]


def _shift_week(dt_str: str, weeks: int = -1) -> str:
    """ISO8601 timestamp를 weeks만큼 이동"""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    shifted = dt + timedelta(weeks=weeks)
    return shifted.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def log_query_tool(
    time_range: dict,               # {"start": "ISO8601", "end": "ISO8601"}
    target: str | None = None,      # 호스트명 (예: SSO_01) 또는 None (전체)
    log_types: list[str] | None = None,  # ["swg_lib", "catalina", "smps_stats"] or None(전체)
    compare_baseline: bool = False, # True: 전주 동일 시점 데이터 함께 반환
    limit: int = 500,
) -> dict:
    """
    SQLite에서 로그 조회.

    Args:
        time_range: {"start": "2026-06-22T09:00:00.000Z", "end": "2026-06-22T09:10:00.000Z"}
        target: 호스트명 필터 (None이면 전체)
        log_types: 조회할 로그 타입 목록 (None이면 전체)
        compare_baseline: True면 전주 동일 시점 데이터도 함께 반환
        limit: 타입별 최대 조회 건수

    Returns:
        {
            "current": {
                "swg_lib": [...],
                "catalina": [...],
                "smps_stats": [...],
                "time_range": {"start": ..., "end": ...}
            },
            "baseline": {  # compare_baseline=True일 때만
                "swg_lib": [...],
                "catalina": [...],
                "smps_stats": [...],
                "time_range": {"start": ..., "end": ...}
            } | None
        }
    """
    start = time_range["start"]
    end = time_range["end"]
    types = log_types or ["swg_lib", "catalina", "smps_stats"]

    conn = _get_conn()
    cur = conn.cursor()

    def fetch(s, e):
        result = {}
        if "swg_lib" in types:
            result["swg_lib"] = _query_swg_lib(cur, target, s, e, limit)
        if "catalina" in types:
            result["catalina"] = _query_catalina(cur, target, s, e, limit)
        if "smps_stats" in types:
            result["smps_stats"] = _query_smps_stats(cur, target, s, e, limit)
        return result

    current = fetch(start, end)
    current["time_range"] = {"start": start, "end": end}

    baseline = None
    if compare_baseline:
        b_start = _shift_week(start, weeks=-1)
        b_end = _shift_week(end, weeks=-1)
        baseline = fetch(b_start, b_end)
        baseline["time_range"] = {"start": b_start, "end": b_end}

    conn.close()

    # 건수 출력
    for log_type in types:
        curr_count = len(current.get(log_type, []))
        base_count = len(baseline.get(log_type, [])) if baseline else "-"
        print(f"  log_query_tool [{log_type}] 현재: {curr_count}건 / 기준: {base_count}건")

    return {"current": current, "baseline": baseline}


if __name__ == "__main__":
    # 동작 테스트
    result = log_query_tool(
        time_range={
            "start": "2026-06-22T03:00:00.000Z",
            "end": "2026-06-22T04:00:00.000Z",
        },
        compare_baseline=True,
        limit=10,
    )
    print(f"\n현재 swg_lib 첫 번째 레코드: {result['current']['swg_lib'][0] if result['current']['swg_lib'] else '없음'}")
    print(f"기준 swg_lib 건수: {len(result['baseline']['swg_lib']) if result['baseline'] else 0}")