import os
import base64
import json
import sqlite3
from datetime import datetime
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


def fetch_log_emails(max_results: int = 10) -> list[dict]:
    """Datadog 로그 메일 목록 조회"""
    service = get_gmail_service()
    query = f'from:{SENDER} subject:{SUBJECT_PREFIX}'

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


def save_to_sqlite(emails: list[dict]):
    """수집한 로그 메일을 SQLite에 저장"""
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
            except Exception as e:
                print(f'⚠️ 저장 실패: {e}')

    conn.commit()
    conn.close()
    print(f'✅ SQLite 저장 완료: {db_path}')


if __name__ == '__main__':
    print('📧 Datadog 로그 메일 수집 시작...')
    emails = fetch_log_emails(max_results=10)
    print(f'  수집된 메일: {len(emails)}건')

    for e in emails:
        print(f'  - {e["subject"]} ({len(e["attachments"])}개 첨부)')

    save_to_sqlite(emails)