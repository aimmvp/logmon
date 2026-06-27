from datetime import datetime
from langgraph.graph import StateGraph, END
from src.schemas.state import LogMonState
from src.nodes.classify_input import classify_input
from src.nodes.load_logs import load_logs
from src.nodes.detect_anomaly import detect_anomaly
from src.nodes.generate_alert import generate_alert
from src.nodes.generate_guide import generate_guide
from src.nodes.generate_report import generate_report
from src.nodes.send_slack import send_slack


def should_load(state: LogMonState) -> str:
    """A/B 유형만 로그 수집, C/D는 스킵"""
    if state.get('input_type') in ('A', 'B'):
        return 'load'
    return 'skip_load'


def should_alert(state: LogMonState) -> str:
    return 'alert' if state.get('anomaly_detected') else 'end'


def should_guide(state: LogMonState) -> str:
    """즉시조치 필요 시 SC-002 가이드 생성으로 분기"""
    alert_msg = state.get('alert_message', '')
    if '즉시 조치 필요' in alert_msg or state.get('anomaly_detected'):
        return 'guide'
    return 'end'


def should_report(state: LogMonState) -> str:
    """정상화 완료 시 SC-003 보고서 생성으로 분기"""
    if state.get('status') == '정상화완료':
        return 'report'
    return 'end'


def build_graph():
    graph = StateGraph(LogMonState)

    # ── 노드 등록 ──────────────────────────────────────────────────────────────
    graph.add_node('classify_input', classify_input)
    graph.add_node('load_logs', load_logs)
    graph.add_node('detect_anomaly', detect_anomaly)
    graph.add_node('generate_alert', generate_alert)
    graph.add_node('generate_guide', generate_guide)
    graph.add_node('generate_report', generate_report)
    graph.add_node('send_slack', send_slack)

    # ── 엣지 연결 ──────────────────────────────────────────────────────────────
    graph.set_entry_point('classify_input')
    graph.add_conditional_edges(
        'classify_input',
        should_load,
        {'load': 'load_logs', 'skip_load': 'generate_guide'}
    )
    graph.add_edge('load_logs', 'detect_anomaly')
    graph.add_conditional_edges(
        'detect_anomaly',
        should_alert,
        {'alert': 'generate_alert', 'end': END}
    )
    # generate_alert → 즉시조치 필요 시 generate_guide, 아니면 send_slack
    graph.add_conditional_edges(
        'generate_alert',
        should_guide,
        {'guide': 'generate_guide', 'end': 'send_slack'}
    )
    graph.add_conditional_edges(
        'generate_guide',
        should_report,
        {'report': 'generate_report', 'end': 'send_slack'}
    )
    graph.add_edge('generate_report', 'send_slack')
    graph.add_edge('send_slack', END)

    return graph.compile()


def _default_state() -> dict:
    return {
        'run_at': datetime.now().isoformat(),
        'input_type': None,
        'batch_trigger': True,
        'operator_input': None,
        'report_requested': False,
        'swg_lib_logs': [],
        'catalina_logs': [],
        'smps_stats_logs': [],
        'anomaly_detected': False,
        'anomaly_summary': '',
        'anomaly_details': [],
        'alert_message': '',
        # SC-002 필드
        'incident_id': None,
        'iteration_count': 0,
        'status': '정상',
        'action_history': [],
        'rag_results': [],
        'guide_message': '',
        'normalized_at': '',
    }


if __name__ == '__main__':
    print('🚀 SC-001 이상 감지 배치 시작')
    app = build_graph()
    result = app.invoke(_default_state())
    print('\n✅ 완료')
    print(f'이상 감지: {result["anomaly_detected"]}')
    print(f'요약: {result["anomaly_summary"]}')
    if result.get('incident_id'):
        print(f'장애 ID: {result["incident_id"]}')
        print(f'가이드: {result["guide_message"][:200]}...')