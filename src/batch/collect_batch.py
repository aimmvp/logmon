"""
Gmail 로그 수집 배치 — 1시간 간격으로 신규 메일만 SQLite에 저장.

실행:
    python src/batch/collect_batch.py          # 스케줄러 모드 (1시간 간격)
    python src/batch/collect_batch.py --once   # 단건 실행 후 종료
"""
import sys
import os
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env')

from src.tools.gmail_collector import fetch_log_emails, save_to_sqlite, get_last_collected_date

os.makedirs(ROOT / 'data', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / 'data' / 'collect_batch.log'),
    ],
)
log = logging.getLogger(__name__)


def collect_once():
    db_path = os.getenv('SQLITE_DB_PATH')
    if not db_path:
        log.error('SQLITE_DB_PATH 환경변수가 설정되지 않았습니다.')
        sys.exit(1)

    since = get_last_collected_date(db_path)
    if since:
        log.info('마지막 수집: %s — 이후 메일만 조회', since.strftime('%Y-%m-%d %H:%M'))
    else:
        log.info('첫 실행 — 전체 메일 조회')

    emails = fetch_log_emails(max_results=50, since=since)
    log.info('조회된 메일: %d건', len(emails))

    if not emails:
        log.info('신규 메일 없음')
        return

    saved, skipped = save_to_sqlite(emails)
    log.info('저장: %d건 / 중복 스킵: %d건', saved, skipped)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='단건 실행 후 종료')
    args = parser.parse_args()

    if args.once:
        collect_once()
    else:
        import schedule
        import time

        log.info('스케줄러 시작 — 1시간 간격으로 실행합니다. 종료: Ctrl+C')
        collect_once()  # 시작 시 즉시 1회 실행
        schedule.every(1).hours.do(collect_once)

        while True:
            schedule.run_pending()
            time.sleep(60)
