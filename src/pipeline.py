from datetime import datetime
from src.tools.gmail_collector import fetch_log_emails, save_to_sqlite
from src.tools.log_parser import parse_and_save
from src.main import build_graph


def run_pipeline():
    print(f'\n{"="*50}')
    print(f'🕐 파이프라인 시작: {datetime.now().isoformat()}')
    print(f'{"="*50}')

    # 1. Gmail 수집
    print('\n📧 [1/3] Gmail 로그 수집')
    emails = fetch_log_emails(max_results=10)
    print(f'  수집된 메일: {len(emails)}건')
    save_to_sqlite(emails)

    # 2. 파싱
    print('\n🔍 [2/3] 로그 파싱')
    parse_and_save()

    # 3. 이상 감지
    print('\n🤖 [3/3] 이상 감지 (SC-001)')
    app = build_graph()
    result = app.invoke({
        'run_at': datetime.now().isoformat(),
        'swg_lib_logs': [],
        'catalina_logs': [],
        'smps_stats_logs': [],
        'anomaly_detected': False,
        'anomaly_summary': '',
        'anomaly_details': [],
        'alert_message': '',
    })

    print(f'\n✅ 파이프라인 완료')
    print(f'  이상 감지: {result["anomaly_detected"]}')
    print(f'  요약: {result["anomaly_summary"]}')


if __name__ == '__main__':
    run_pipeline()
