import sqlite3
conn = sqlite3.connect('./data/sqlite/logmon.db')
cur = conn.cursor()
cur.execute('SELECT id, subject, filename, date FROM log_emails')
rows = cur.fetchall()
print(f'총 {len(rows)}건')
for r in rows:
    print(f'  [{r[0]}] {r[1]} | {r[2]} | {r[3]}')
conn.close()
