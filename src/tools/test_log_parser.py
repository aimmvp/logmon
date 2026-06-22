import sqlite3
conn = sqlite3.connect('./data/sqlite/logmon.db')
cur = conn.cursor()

# 각 테이블 건수
for table in ['log_swg_lib', 'log_catalina', 'log_smps_stats']:
    cur.execute(f'SELECT COUNT(*) FROM {table}')
    print(f'{table}: {cur.fetchone()[0]}건')

# 샘플 1건씩
print()
print('--- swg_lib 샘플 ---')
cur.execute('SELECT timestamp, host, auth_type, auth_result, auth_reason, user_id FROM log_swg_lib LIMIT 1')
print(cur.fetchone())

print('--- catalina 샘플 ---')
cur.execute('SELECT timestamp, host, log_level, log_message FROM log_catalina LIMIT 1')
print(cur.fetchone())

print('--- smps_stats 샘플 ---')
cur.execute('SELECT timestamp, host, response_time, busy_threads, exceeded_limit, core_result FROM log_smps_stats LIMIT 1')
print(cur.fetchone())

conn.close()