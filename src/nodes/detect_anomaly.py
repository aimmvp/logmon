import os
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from openai import AzureOpenAI
from src.schemas.state import LogMonState
from src.utils.prompt_loader import load_system_context

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv('AZURE_OPENAI_API_KEY'),
    azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
    api_version=os.getenv('AZURE_OPENAI_API_VERSION'),
)
DEPLOYMENT = os.getenv('AZURE_OPENAI_DEPLOYMENT')
THRESHOLD_PATH = "./data/threshold_profile.json"


def _load_threshold_profile() -> dict:
    if not os.path.exists(THRESHOLD_PATH):
        return {}
    with open(THRESHOLD_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_current_bucket() -> str:
    """현재 시각 기준 10분 버킷 (KST) — 폴백용"""
    kst_now = datetime.now(timezone.utc) + timedelta(hours=9)
    minute_bucket = (kst_now.minute // 10) * 10
    return f"{kst_now.hour:02d}:{minute_bucket:02d}"


WEEKDAY_MAP = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def _get_log_bucket(smps_logs: list[dict]) -> tuple[str, str]:
    """smps_stats 로그의 최신 timestamp 기준 (weekday, bucket) 반환 (KST)"""
    if not smps_logs:
        kst_now = datetime.now(timezone.utc) + timedelta(hours=9)
        minute_bucket = (kst_now.minute // 10) * 10
        return WEEKDAY_MAP[kst_now.weekday()], f"{kst_now.hour:02d}:{minute_bucket:02d}"
    try:
        latest_ts = sorted([r["timestamp"] for r in smps_logs])[-1]
        dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
        kst = dt + timedelta(hours=9)
        minute_bucket = (kst.minute // 10) * 10
        return WEEKDAY_MAP[kst.weekday()], f"{kst.hour:02d}:{minute_bucket:02d}"
    except Exception:
        kst_now = datetime.now(timezone.utc) + timedelta(hours=9)
        minute_bucket = (kst_now.minute // 10) * 10
        return WEEKDAY_MAP[kst_now.weekday()], f"{kst_now.hour:02d}:{minute_bucket:02d}"


def _get_bucket_thresholds(profile: dict, weekday: str, bucket: str) -> str:
    hosts = profile.get("hosts", {})
    if not hosts:
        return "임계치 프로파일 없음 — 상대적 패턴으로만 판단"

    lines = [f"현재 시간대 ({weekday} {bucket} KST) 호스트별 임계치:"]
    for host, weekdays in sorted(hosts.items()):
        buckets = weekdays.get(weekday, {})
        if bucket not in buckets:
            continue
        b = buckets[bucket]
        rt = b.get("response_time", {})
        bt = b.get("busy_threads", {})
        af = b.get("auth_fail_rate", {})
        lines.append(
            f"- {host}: "
            f"RT(모니터링 판단기준={rt.get('monitor_threshold')}ms초과, 즉시조치 판단기준={rt.get('critical_threshold')}ms초과) | "
            f"BusyThreads(모니터링 판단기준={bt.get('monitor_threshold')}초과, 즉시조치 판단기준={bt.get('critical_threshold')}초과) | "
            f"인증실패율(모니터링 판단기준={af.get('monitor_threshold')}%초과, 즉시조치 판단기준={af.get('critical_threshold')}%초과)"
        )
    return "\n".join(lines) if len(lines) > 1 else "임계치 프로파일 없음 — 상대적 패턴으로만 판단"


def detect_anomaly(state: LogMonState) -> LogMonState:
    """LLM 기반 이상 감지 (임계치 프로파일 참조)"""
    system_context = load_system_context()
    profile = _load_threshold_profile()
    weekday, bucket = _get_log_bucket(state.get('smps_stats_logs', []))
    threshold_text = _get_bucket_thresholds(profile, weekday, bucket)

    prompt = f"""
{system_context}
---
당신은 SSO 서비스 운영 전문가입니다.
위 시스템 명세와 아래 임계치 기준을 참고하여 로그 데이터를 분석하고 이상 징후를 감지하세요.

## 임계치 기준 (LLM 생성, 기준 기간: {profile.get('baseline_period', '미설정')})
{threshold_text}

## swg_lib 로그 (인증 로그)
{json.dumps(state['swg_lib_logs'][:50], ensure_ascii=False, indent=2)}

## catalina 로그 (애플리케이션 로그)
{json.dumps(state['catalina_logs'][:50], ensure_ascii=False, indent=2)}

## smps_stats 로그 (SiteMinder 성능 지표)
{json.dumps(state['smps_stats_logs'][:50], ensure_ascii=False, indent=2)}

## 판단 기준 (반드시 준수)
- **정상**: 모든 지표가 모니터링 판단기준 이내
- **모니터링**: 실제 측정값이 모니터링 판단기준을 **명확히 초과**한 경우만 해당. 근접하거나 초과 가능성만으로는 모니터링 판단 불가
- **즉시조치**: 실제 측정값이 즉시조치 판단기준을 **명확히 초과**한 경우만 해당
- 판단 시 반드시 "실제 측정값 XX > 판단기준 YY" 형태로 근거 명시
- 측정값이 판단기준 미만이면 반드시 정상으로 판단
- smps_stats: 각 호스트별 response_time, busy_threads 최신값과 판단기준 비교
- swg_lib: 인증 실패율 실측값과 판단기준 비교. auth_result=-1 건수/비율 명시
- catalina: ERROR/WARN 레벨, sendOtpPwd/sendSmsByMqPut 오류 확인

## 응답 형식 (JSON만 반환)
{{
  "anomaly_detected": true/false,
  "anomaly_level": "정상/모니터링/즉시조치",
  "anomaly_summary": "이상 감지 요약 (없으면 '이상 없음')",
  "threshold_reference": "{weekday} {bucket} 버킷 임계치 기준 적용",
  "anomaly_details": [
    {{
      "log_type": "swg_lib/catalina/smps_stats",
      "host": "호스트명",
      "description": "이상 내용 (임계치 초과 수치 포함)",
      "severity": "HIGH/MEDIUM/LOW"
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=1000,
        response_format={'type': 'json_object'},
    )

    result = json.loads(response.choices[0].message.content)
    print(f'  이상 감지: {result["anomaly_detected"]} ({result.get("anomaly_level", "")})')
    print(f'  요약: {result["anomaly_summary"]}')

    return {
        **state,
        'anomaly_detected': result.get('anomaly_detected', False),
        'anomaly_level': result.get('anomaly_level', '정상'),
        'anomaly_summary': result.get('anomaly_summary', ''),
        'anomaly_details': result.get('anomaly_details', []),
    }