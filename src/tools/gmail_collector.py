import os
import base64
import sqlite3
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
SENDER = 'no-reply@dtdg.co'
SUBJECT_PREFIX = '[Logs Report]'


def get_gmail_service():
    creds = None
    token_path = os.getenv('GMAIL_TOKEN_PATH')
    credentials_path = os.getenv('GMAIL_CREDENTIALS_PATH')

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def get_last_collected_date(db_path: str) -> datetime | None:
    """DB에서 마지막으로 저장된 메일 날짜 조회"""
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT MAX(date) FROM log_emails")
        row = cur.fetchone()
        if row and row[0]:
            return parsedate_to_datetime(row[0])
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return None


def fetch_log_emails(max_results: int = 50, since: datetime | None = None) -> list[dict]:
    """Datadog 로그 메일 목록 조회. since 지정 시 해당 날짜 이후 메일만 조회."""
    service = get_gmail_service()
    query = f'from:{SENDER} subject:{SUBJECT_PREFIX}'
    if since:
        # Gmail after: 필터는 YYYY/MM/DD 형식 사용
        query += f' after:{since.strftime("%Y/%m/%d")}'

    result = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=max_results
    ).execute()

    messages = result.get('messages', [])
    emails = []

    for msg in messages:
        msg_detail = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='full'
        ).execute()

        headers = {h['name']: h['value'] for h in msg_detail['payload']['headers']}
        subject = headers.get('Subject', '')
        date = headers.get('Date', '')

        # CSV 첨부파일 추출
        attachments = []
        parts = msg_detail['payload'].get('parts', [])
        for part in parts:
            if part.get('filename', '').endswith('.csv'):
                att_id = part['body'].get('attachmentId')
                if att_id:
                    att = service.users().messages().attachments().get(
                        userId='me',
                        messageId=msg['id'],
                        id=att_id
                    ).execute()
                    csv_data = base64.urlsafe_b64decode(att['data']).decode('utf-8')
                    attachments.append({
                        'filename': part['filename'],
                        'content': csv_data
                    })

        emails.append({
            'message_id': msg['id'],
            'subject': subject,
            'date': date,
            'attachments': attachments
        })

    return emails


def save_to_sqlite(emails: list[dict]) -> tuple[int, int]:
    """수집한 로그 메일을 SQLite에 저장. (저장건수, 중복스킵건수) 반환."""
    db_path = os.getenv('SQLITE_DB_PATH')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS log_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            subject TEXT,
            date TEXT,
            filename TEXT,
            content TEXT,
            created_at TEXT
        )
    ''')

    saved = skipped = 0
    for email in emails:
        for att in email['attachments']:
            try:
                cur.execute('''
                    INSERT OR IGNORE INTO log_emails
                    (message_id, subject, date, filename, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    email['message_id'],
                    email['subject'],
                    email['date'],
                    att['filename'],
                    att['content'],
                    datetime.now().isoformat()
                ))
                if cur.rowcount:
                    saved += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f'⚠️ 저장 실패: {e}')

    conn.commit()
    conn.close()
    return saved, skipped


if __name__ == '__main__':
    print('📧 Datadog 로그 메일 수집 시작...')
    emails = fetch_log_emails(max_results=10)
    print(f'  수집된 메일: {len(emails)}건')
    for e in emails:
        print(f'  - {e["subject"]} ({len(e["attachments"])}개 첨부)')
    saved, skipped = save_to_sqlite(emails)
    print(f'✅ 저장: {saved}건 / 중복 스킵: {skipped}건')