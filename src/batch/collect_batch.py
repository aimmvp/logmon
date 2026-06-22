"""
Gmail 로그 수집 배치 — 마지막 수집 이후 신규 메일만 가져와 SQLite에 저장.
cron: 0 * * * * /path/to/venv/bin/python /path/to/src/batch/collect_batch.py
"""
import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / '.env')

from src.tools.gmail_collector import fetch_log_emails, save_to_sqlite, get_last_collected_date

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / 'data' / 'collect_batch.log'),
    ],
)
log = logging.getLogger(__name__)


def run():
    db_path = os.getenv('SQLITE_DB_PATH')
    if not db_path:
        log.error('SQLITE_DB_PATH 환경변수가 설정되지 않았습니다.')
        sys.exit(1)

    since = get_last_collected_date(db_path)
    if since:
        log.info('마지막 수집 날짜: %s — 이후 메일만 조회합니다.', since.strftime('%Y-%m-%d %H:%M'))
    else:
        log.info('첫 실행 — 전체 메일 조회합니다.')

    emails = fetch_log_emails(max_results=50, since=since)
    log.info('조회된 메일: %d건', len(emails))

    if not emails:
        log.info('신규 메일 없음. 종료합니다.')
        return

    saved, skipped = save_to_sqlite(emails)
    log.info('저장: %d건 / 중복 스킵: %d건', saved, skipped)


if __name__ == '__main__':
    run()
