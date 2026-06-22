import os
import csv
import re
import sqlite3
import io
from datetime import datetime
from dotenv import load_dotenv
from src.utils.host_mapper import map_host

load_dotenv()

DB_PATH = os.getenv('SQLITE_DB_PATH')


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_tables():
    """파싱 결과 테이블 초기화"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS log_swg_lib (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER,
            status TEXT,
            timestamp TEXT,
            host TEXT,
            service TEXT,
            log_time TEXT,
            auth_type TEXT,
            auth_result INTEGER,
            auth_reason INTEGER,
            user_id TEXT,
            status_code INTEGER,
            co_cl_cd TEXT,
            created_at TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS log_catalina (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER,
            status TEXT,
            timestamp TEXT,
            host TEXT,
            service TEXT,
            thread TEXT,
            log_level TEXT,
            logger TEXT,
            log_message TEXT,
            created_at TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS log_smps_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER,
            status TEXT,
            timestamp TEXT,
            host TEXT,
            service TEXT,
            msgs INTEGER,
            throughput REAL,
            response_time REAL,
            wait_time_in_queue REAL,
            max_hp_msg INTEGER,
            max_np_msg INTEGER,
            current_depth INTEGER,
            max_depth INTEGER,
            current_threads INTEGER,
            max_threads INTEGER,
            busy_threads INTEGER,
            current_connections INTEGER,
            max_connections INTEGER,
            exceeded_limit INTEGER,
            core_result TEXT,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()


def parse_swg_lib_message(message: str) -> dict:
    """swg_lib message 파싱
    예: 20260622115942,AuthType=PWD,AuthResult=0,AuthReason=32000,ID=E007640007,STATUS=0,CO_CL_CD=B
    """
    result = {}
    try:
        parts = message.split(',')
        result['log_time'] = parts[0].strip() if parts else None
        for part in parts[1:]:
            if '=' in part:
                k, v = part.split('=', 1)
                result[k.strip()] = v.strip()
    except Exception:
        pass
    return result


def parse_catalina_message(message: str) -> dict:
    """catalina message 파싱
    예: 11:59:42.404 [ajp-bio-...] INFO  com.skt...OTPService[method:356] - 내용
    """
    result = {}
    try:
        pattern = r'(\S+)\s+\[([^\]]+)\]\s+(\w+)\s+(\S+)\s+-\s+(.*)'
        m = re.match(pattern, message)
        if m:
            result['thread'] = m.group(2)
            result['log_level'] = m.group(3)
            result['logger'] = m.group(4)
            result['log_message'] = m.group(5)
        else:
            result['log_level'] = 'INFO'
            result['log_message'] = message
    except Exception:
        result['log_message'] = message
    return result


def parse_smps_stats_message(message: str) -> dict:
    """smps_stats message 파싱
    예: [Mon Jun 22 2026 11:59:01] Msgs=870881478 Throughput=309.088136 ...
    """
    result = {}
    try:
        pairs = re.findall(r'(\w+)=([\d.]+|[A-Z])', message)
        for k, v in pairs:
            result[k] = v
    except Exception:
        pass
    return result


def detect_log_type(subject: str) -> str | None:
    """메일 제목에서 로그 타입 감지"""
    subject_lower = subject.lower()
    if 'swg_lib' in subject_lower:
        return 'swg_lib'
    elif 'catalina' in subject_lower:
        return 'catalina'
    elif 'smps_stats' in subject_lower:
        return 'smps_stats'
    return None


def parse_and_save():
    """log_emails 에서 읽어서 타입별 테이블에 파싱 저장"""
    init_tables()
    conn = get_conn()
    cur = conn.cursor()

    cur.execute('SELECT id, subject, filename, content FROM log_emails')
    rows = cur.fetchall()
    conn.close()

    stats = {'swg_lib': 0, 'catalina': 0, 'smps_stats': 0, 'skip': 0}

    for email_id, subject, filename, content in rows:
        log_type = detect_log_type(subject)
        if not log_type:
            stats['skip'] += 1
            continue

        reader = csv.DictReader(io.StringIO(content))
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now().isoformat()

        for row in reader:
            status = row.get('status', '')
            timestamp = row.get('timestamp', '')
            host = map_host(row.get('host', ''))
            service = row.get('service', '')
            message = row.get('message', '')

            if log_type == 'swg_lib':
                p = parse_swg_lib_message(message)
                cur.execute('''
                    INSERT INTO log_swg_lib
                    (email_id, status, timestamp, host, service,
                     log_time, auth_type, auth_result, auth_reason,
                     user_id, status_code, co_cl_cd, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    email_id, status, timestamp, host, service,
                    p.get('log_time'),
                    p.get('AuthType'),
                    int(p.get('AuthResult', -1)),
                    int(p.get('AuthReason', -1)),
                    p.get('ID'),
                    int(p.get('STATUS', -1)),
                    p.get('CO_CL_CD'),
                    now
                ))
                stats['swg_lib'] += 1

            elif log_type == 'catalina':
                p = parse_catalina_message(message)
                cur.execute('''
                    INSERT INTO log_catalina
                    (email_id, status, timestamp, host, service,
                     thread, log_level, logger, log_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    email_id, status, timestamp, host, service,
                    p.get('thread'),
                    p.get('log_level'),
                    p.get('logger'),
                    p.get('log_message'),
                    now
                ))
                stats['catalina'] += 1

            elif log_type == 'smps_stats':
                p = parse_smps_stats_message(message)
                cur.execute('''
                    INSERT INTO log_smps_stats
                    (email_id, status, timestamp, host, service,
                     msgs, throughput, response_time, wait_time_in_queue,
                     max_hp_msg, max_np_msg, current_depth, max_depth,
                     current_threads, max_threads, busy_threads,
                     current_connections, max_connections,
                     exceeded_limit, core_result, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    email_id, status, timestamp, host, service,
                    int(p.get('Msgs', 0)),
                    float(p.get('Throughput', 0)),
                    float(p.get('Response_Time', 0)),
                    float(p.get('Wait_Time_In_Queue', 0)),
                    int(p.get('Max_HP_Msg', 0)),
                    int(p.get('Max_NP_Msg', 0)),
                    int(p.get('Current_Depth', 0)),
                    int(p.get('Max_Depth', 0)),
                    int(p.get('Current_Threads', 0)),
                    int(p.get('Max_Threads', 0)),
                    int(p.get('Busy_Threads', 0)),
                    int(p.get('Current_Connections', 0)),
                    int(p.get('Max_Connections', 0)),
                    int(p.get('Exceeded_Limit', 0)),
                    p.get('Core_Result'),
                    now
                ))
                stats['smps_stats'] += 1

        conn.commit()
        conn.close()

    print('✅ 파싱 완료')
    print(f'  swg_lib   : {stats["swg_lib"]}건')
    print(f'  catalina  : {stats["catalina"]}건')
    print(f'  smps_stats: {stats["smps_stats"]}건')
    print(f'  스킵      : {stats["skip"]}건')


if __name__ == '__main__':
    parse_and_save()