import os
import json
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


def detect_anomaly(state: LogMonState) -> LogMonState:
    """LLM 기반 이상 감지"""

    system_context = load_system_context()

    prompt = f"""
{system_context}

---

당신은 SSO 서비스 운영 전문가입니다.
위 시스템 명세를 참고하여 아래 3가지 로그 데이터를 분석하고 이상 징후를 감지하세요.

## swg_lib 로그 (인증 로그)
{json.dumps(state['swg_lib_logs'][:50], ensure_ascii=False, indent=2)}

## catalina 로그 (애플리케이션 로그)
{json.dumps(state['catalina_logs'][:50], ensure_ascii=False, indent=2)}

## smps_stats 로그 (SiteMinder 성능 지표)
{json.dumps(state['smps_stats_logs'][:50], ensure_ascii=False, indent=2)}

## 분석 기준
- swg_lib: 인증 실패(auth_result=-1) 급증, 특정 auth_reason 패턴
- catalina: ERROR/WARN 레벨 로그, 예외 발생, sendOtpPwd/sendSmsByMqPut 오류
- smps_stats: response_time 급증, exceeded_limit > 0, core_result = Y

## 응답 형식 (JSON만 반환)
{{
  "anomaly_detected": true/false,
  "anomaly_summary": "이상 감지 요약 (없으면 '이상 없음')",
  "anomaly_details": [
    {{
      "log_type": "swg_lib/catalina/smps_stats",
      "host": "호스트명",
      "description": "이상 내용",
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
    print(f'  이상 감지: {result["anomaly_detected"]}')
    print(f'  요약: {result["anomaly_summary"]}')

    return {
        **state,
        'anomaly_detected': result.get('anomaly_detected', False),
        'anomaly_summary': result.get('anomaly_summary', ''),
        'anomaly_details': result.get('anomaly_details', []),
    }