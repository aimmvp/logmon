from datetime import datetime
from langgraph.graph import StateGraph, END
from src.schemas.state import LogMonState
from src.nodes.load_logs import load_logs
from src.nodes.detect_anomaly import detect_anomaly
from src.nodes.generate_alert import generate_alert
from src.nodes.send_slack import send_slack


def should_alert(state: LogMonState) -> str:
    return 'alert' if state.get('anomaly_detected') else 'end'


def build_graph():
    graph = StateGraph(LogMonState)

    graph.add_node('load_logs', load_logs)
    graph.add_node('detect_anomaly', detect_anomaly)
    graph.add_node('generate_alert', generate_alert)
    graph.add_node('send_slack', send_slack)

    graph.set_entry_point('load_logs')
    graph.add_edge('load_logs', 'detect_anomaly')
    graph.add_conditional_edges(
        'detect_anomaly',
        should_alert,
        {'alert': 'generate_alert', 'end': END}
    )
    graph.add_edge('generate_alert', 'send_slack')
    graph.add_edge('send_slack', END)

    return graph.compile()


if __name__ == '__main__':
    print('🚀 SC-001 이상 감지 배치 시작')
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
    print('\n✅ 완료')
    print(f'이상 감지: {result["anomaly_detected"]}')
    print(f'요약: {result["anomaly_summary"]}')
