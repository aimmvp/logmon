"""
incident_log_tool
- save_progress: SC-002 진행 이력 SQLite 저장
- save_report: SC-003 결과 보고서 SQLite 저장 + Chroma 임베딩 (RAG 자동 보강)
"""

import os
import json
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DB_PATH = os.getenv("SQLITE_DB_PATH")
CHROMA_PATH = "./data/chroma"
COLLECTION_INCIDENT = "incident_history"
EMBEDDING_MODEL = "text-embedding-3-small"

_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY_INGEST"))


# ── DB 초기화 ─────────────────────────────────────────────────────────────────
def _init_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS incident_progress (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id  TEXT NOT NULL,
            iteration    INTEGER DEFAULT 1,
            status       TEXT,
            summary      TEXT,
            guide        TEXT,
            operator_feedback TEXT,
            created_at   TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS incident_report (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id            TEXT UNIQUE NOT NULL,
            root_cause             TEXT,
            actions_taken          TEXT,   -- JSON array
            before_after_comparison TEXT,  -- JSON object
            remaining_risks        TEXT,   -- JSON array
            prevention_plan        TEXT,   -- JSON array
            summary                TEXT,
            created_at             TEXT
        )
    """)

    conn.commit()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    _init_tables(conn)
    return conn


# ── save_progress ─────────────────────────────────────────────────────────────
def _save_progress(
    incident_id: str,
    iteration: int,
    status: str,
    summary: str,
    guide: str,
    operator_feedback: str = "",
) -> dict:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO incident_progress
        (incident_id, iteration, status, summary, guide, operator_feedback, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        incident_id, iteration, status, summary, guide,
        operator_feedback, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()
    return {"status": "saved", "incident_id": incident_id}


# ── save_report ───────────────────────────────────────────────────────────────
def _save_report(
    incident_id: str,
    root_cause: str,
    actions_taken: list[str],
    before_after_comparison: dict,
    remaining_risks: list[str],
    prevention_plan: list[str],
    summary: str,
) -> dict:
    # 1. SQLite 저장
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO incident_report
        (incident_id, root_cause, actions_taken, before_after_comparison,
         remaining_risks, prevention_plan, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        incident_id,
        root_cause,
        json.dumps(actions_taken, ensure_ascii=False),
        json.dumps(before_after_comparison, ensure_ascii=False),
        json.dumps(remaining_risks, ensure_ascii=False),
        json.dumps(prevention_plan, ensure_ascii=False),
        summary,
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

    # 2. Chroma 임베딩 → RAG 자동 보강
    _embed_to_chroma(
        incident_id=incident_id,
        root_cause=root_cause,
        actions_taken=actions_taken,
        remaining_risks=remaining_risks,
        prevention_plan=prevention_plan,
        summary=summary,
    )

    return {"status": "saved", "incident_id": incident_id}


def _embed_to_chroma(
    incident_id: str,
    root_cause: str,
    actions_taken: list[str],
    remaining_risks: list[str],
    prevention_plan: list[str],
    summary: str,
) -> None:
    """보고서를 Chroma incident_history 컬렉션에 임베딩하여 RAG 보강"""
    try:
        from chromadb import PersistentClient
        from src.scripts.ingest_siteminder import OpenAIEmbeddingFunction, EmbeddingFunction, Documents, Embeddings

        # 1 incident = 1 chunk (증상-원인-조치-결과 통합)
        chunk_text = f"""[장애 이력] {incident_id}
요약: {summary}
원인: {root_cause}
조치: {' / '.join(actions_taken)}
남은 리스크: {' / '.join(remaining_risks)}
재발 방지: {' / '.join(prevention_plan)}"""

        embed_fn = OpenAIEmbeddingFunction(
            client=_openai_client,
            model=EMBEDDING_MODEL,
        )

        client = PersistentClient(path=CHROMA_PATH)
        collection = client.get_or_create_collection(
            name=COLLECTION_INCIDENT,
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        collection.upsert(
            ids=[incident_id],
            documents=[chunk_text],
            metadatas=[{"incident_id": incident_id, "created_at": datetime.now().isoformat()}],
        )
        print(f"  Chroma 임베딩 완료: {incident_id}")
    except Exception as e:
        print(f"  ⚠️ Chroma 임베딩 실패 (SQLite 저장은 완료): {e}")


# ── public interface ──────────────────────────────────────────────────────────
def incident_log_tool(
    incident_id: str,
    mode: str,                          # save_progress | save_report
    summary: str = "",
    guide: str = "",
    operator_feedback: str = "",
    iteration: int = 1,
    status: str = "조치중",
    root_cause: str = "",
    actions_taken: list[str] = None,
    before_after_comparison: dict = None,
    remaining_risks: list[str] = None,
    prevention_plan: list[str] = None,
) -> dict:
    """
    SC-002/SC-003 장애 이력 저장 Tool.

    Args:
        incident_id: 장애 식별자
        mode: save_progress (중간 이력) | save_report (최종 보고서)
        --- save_progress 전용 ---
        summary: 이번 차수 가이드 요약
        guide: 전체 가이드 텍스트
        operator_feedback: 운영자 조치 결과
        iteration: 반복 차수
        status: 현재 상태
        --- save_report 전용 ---
        root_cause: 근본 원인
        actions_taken: 수행된 조치 목록
        before_after_comparison: 조치 전후 비교 (dict)
        remaining_risks: 남은 리스크 목록
        prevention_plan: 재발 방지 방안 목록
    """
    if mode == "save_progress":
        return _save_progress(
            incident_id=incident_id,
            iteration=iteration,
            status=status,
            summary=summary,
            guide=guide,
            operator_feedback=operator_feedback,
        )
    elif mode == "save_report":
        return _save_report(
            incident_id=incident_id,
            root_cause=root_cause,
            actions_taken=actions_taken or [],
            before_after_comparison=before_after_comparison or {},
            remaining_risks=remaining_risks or [],
            prevention_plan=prevention_plan or [],
            summary=summary,
        )
    else:
        raise ValueError(f"mode는 'save_progress' 또는 'save_report'여야 합니다: {mode}")


def get_incident_progress(incident_id: str) -> list[dict]:
    """SC-003에서 전체 진행 이력 조회"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT iteration, status, summary, guide, operator_feedback, created_at
        FROM incident_progress
        WHERE incident_id = ?
        ORDER BY iteration ASC
    """, (incident_id,))
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "iteration": r[0], "status": r[1], "summary": r[2],
            "guide": r[3], "operator_feedback": r[4], "created_at": r[5],
        }
        for r in rows
    ]


if __name__ == "__main__":
    # 동작 테스트
    test_id = "INC-TEST-001"

    # save_progress 테스트
    result = incident_log_tool(
        incident_id=test_id,
        mode="save_progress",
        iteration=1,
        status="조치중",
        summary="swg_lib 인증 실패 급증",
        guide="세션풀 재설정 권장",
        operator_feedback="",
    )
    print(f"save_progress: {result}")

    # save_report 테스트
    result = incident_log_tool(
        incident_id=test_id,
        mode="save_report",
        summary="세션풀 고갈로 인한 인증 실패",
        root_cause="Session Pool 설정값 부족",
        actions_taken=["solctl session-pool reload", "batchctl pause BATCH-REINDEX"],
        before_after_comparison={"response_time": {"before": "3.2s", "after": "0.4s"}},
        remaining_risks=["배치 재개 시 유사 부하 가능성"],
        prevention_plan=["Session Pool 상향 조정", "배치 스케줄 야간으로 변경"],
    )
    print(f"save_report: {result}")

    # 이력 조회 테스트
    history = get_incident_progress(test_id)
    print(f"이력: {history}")