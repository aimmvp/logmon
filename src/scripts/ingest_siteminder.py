"""
SiteMinder PDF RAG Ingest Script
사용법: python -m src.scripts.ingest_siteminder
또는 직접 실행: python ingest_siteminder.py --pdf path/to/pdf
"""

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

import pdfplumber
from chromadb import PersistentClient
from chromadb import EmbeddingFunction, Documents, Embeddings
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── 설정 ────────────────────────────────────────────────────────────────────
CHROMA_PATH = "./data/chroma"
COLLECTION_NAME = "siteminder_manual"
EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_API_KEY_INGEST = os.getenv("OPENAI_API_KEY_INGEST")

# 캐시 경로
CHUNK_CACHE_PATH = "./data/cache/siteminder_chunks.json"

# 청킹 파라미터
CHUNK_SIZE = 500        # 토큰 기준 (단어 수 근사)
CHUNK_OVERLAP = 50
BATCH_SIZE = 100        # Chroma upsert 배치 크기
EMBED_BATCH_SIZE = 100  # 임베딩 API 호출 배치 크기
MAX_RETRIES = 5         # 재시도 횟수
RETRY_WAIT = 10         # 재시도 대기 시간 (초)
BATCH_DELAY = 0         # 배치 간 대기 없음

# 헤딩 패턴 (섹션 경계 감지용)
HEADING_PATTERNS = [
    re.compile(r"^[A-Z][A-Za-z\s\-/]{5,60}$"),          # 대문자 시작 짧은 라인
    re.compile(r"^Chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^Section\s+\d+", re.IGNORECASE),
    re.compile(r"^How to\s+", re.IGNORECASE),
    re.compile(r"^Configure\s+", re.IGNORECASE),
    re.compile(r"^Install\s+", re.IGNORECASE),
    re.compile(r"^Troubleshoot", re.IGNORECASE),
]


def is_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 80:
        return False
    return any(p.match(line) for p in HEADING_PATTERNS)


def extract_pages(pdf_path: str) -> list[dict]:
    """PDF에서 페이지별 텍스트 추출"""
    pages = []
    logger.info(f"PDF 로딩: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        logger.info(f"총 페이지 수: {total}")

        for i, page in enumerate(pdf.pages):
            if i % 500 == 0:
                logger.info(f"  페이지 추출 중... {i}/{total}")

            text = page.extract_text()
            if not text or len(text.strip()) < 30:
                continue

            # 헤더/푸터 제거 (각 페이지 첫째 줄 "Symantec SiteMinder - 12.8" 패턴)
            lines = text.split("\n")
            lines = [
                l for l in lines
                if not re.match(r"^Symantec SiteMinder", l.strip())
                and not re.match(r"^\d+$", l.strip())  # 페이지 번호
            ]
            clean_text = "\n".join(lines).strip()

            if clean_text:
                pages.append({"page": i + 1, "text": clean_text})

    logger.info(f"유효 페이지 수: {len(pages)}")
    return pages



def save_chunks_cache(chunks: list[dict], cache_path: str) -> None:
    """청크 캐시를 JSON으로 저장"""
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    logger.info(f"청크 캐시 저장 완료: {cache_path} ({len(chunks)}개)")


def load_chunks_cache(cache_path: str) -> list[dict]:
    """저장된 청크 캐시 로드"""
    with open(cache_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    logger.info(f"청크 캐시 로드 완료: {cache_path} ({len(chunks)}개)")
    return chunks


def split_into_chunks(pages: list[dict]) -> list[dict]:
    """
    Hierarchical chunking 전략:
    - 섹션 헤딩 감지 → 섹션 경계에서 우선 분할
    - 섹션이 CHUNK_SIZE 초과 시 overlap 포함 추가 분할
    """
    chunks = []
    chunk_id = 0

    current_section = ""
    current_heading = ""
    current_pages = []
    word_count = 0

    def flush(heading, text, pages):
        nonlocal chunk_id
        if not text.strip():
            return
        words = text.split()
        # CHUNK_SIZE 초과 시 재분할
        if len(words) <= CHUNK_SIZE:
            chunks.append({
                "id": f"chunk_{chunk_id:06d}",
                "text": text.strip(),
                "heading": heading,
                "page_start": pages[0] if pages else 0,
                "page_end": pages[-1] if pages else 0,
            })
            chunk_id += 1
        else:
            # sliding window 재분할
            step = CHUNK_SIZE - CHUNK_OVERLAP
            for start in range(0, len(words), step):
                sub = " ".join(words[start: start + CHUNK_SIZE])
                if not sub.strip():
                    continue
                chunks.append({
                    "id": f"chunk_{chunk_id:06d}",
                    "text": sub.strip(),
                    "heading": heading,
                    "page_start": pages[0] if pages else 0,
                    "page_end": pages[-1] if pages else 0,
                })
                chunk_id += 1

    for page_data in pages:
        page_num = page_data["page"]
        for line in page_data["text"].split("\n"):
            if is_heading(line):
                # 섹션 경계 → 누적분 flush
                flush(current_heading, current_section, current_pages)
                current_heading = line.strip()
                current_section = line + "\n"
                current_pages = [page_num]
                word_count = len(line.split())
            else:
                current_section += line + "\n"
                word_count += len(line.split())
                if page_num not in current_pages:
                    current_pages.append(page_num)

                # CHUNK_SIZE 2배 초과 시 중간 flush (섹션이 너무 긴 경우 대비)
                if word_count >= CHUNK_SIZE * 2:
                    flush(current_heading, current_section, current_pages)
                    current_section = ""
                    current_pages = [page_num]
                    word_count = 0

    # 마지막 잔여분 flush
    flush(current_heading, current_section, current_pages)

    logger.info(f"총 청크 수: {len(chunks)}")
    return chunks


def _get_embed_fn() -> "OpenAIEmbeddingFunction":
    """OpenAI 클라이언트 기반 임베딩 함수 반환"""
    return OpenAIEmbeddingFunction(
        client=OpenAI(api_key=OPENAI_API_KEY_INGEST),
        model=EMBEDDING_MODEL,
    )


class OpenAIEmbeddingFunction(EmbeddingFunction):
    """chromadb 내장 대신 OpenAI 직접 클라이언트 사용"""

    def __init__(self, client: OpenAI, model: str):
        self._client = client
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        response = self._client.embeddings.create(
            model=self._model,
            input=input,
        )
        return [item.embedding for item in response.data]


def build_chroma_collection(chunks: list[dict]) -> None:
    """Chroma에 청크 upsert"""
    client = PersistentClient(path=CHROMA_PATH)
    embed_fn = _get_embed_fn()

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    total = len(chunks)
    success_count = 0
    fail_count = 0
    start_time = time.time()
    logger.info(f"Chroma upsert 시작: {total}개 청크 / BATCH_SIZE={BATCH_SIZE} / BATCH_DELAY={BATCH_DELAY}s / RETRY_WAIT={RETRY_WAIT}s")

    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i: i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        chunk_ids = [c["id"] for c in batch]
        elapsed = time.time() - start_time

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                collection.upsert(
                    ids=chunk_ids,
                    documents=[c["text"] for c in batch],
                    metadatas=[
                        {
                            "heading": c["heading"],
                            "page_start": c["page_start"],
                            "page_end": c["page_end"],
                        }
                        for c in batch
                    ],
                )
                success_count += len(batch)
                if i % (BATCH_SIZE * 10) == 0:
                    logger.info(
                        f"  [배치 {batch_num}/{total_batches}] "
                        f"청크 {i}~{i+len(batch)-1} 완료 | "
                        f"누적 성공: {success_count}/{total} | "
                        f"경과: {elapsed:.0f}s"
                    )
                break  # 성공 시 재시도 루프 탈출
            except Exception as e:
                fail_count += 1
                error_type = type(e).__name__
                error_msg = str(e)[:300]  # 너무 긴 HTML 응답 잘라냄
                if attempt == MAX_RETRIES:
                    sep = "=" * 60
                    logger.error(
                        f"{sep}\n"
                        f"[최종 실패] 배치 {batch_num}/{total_batches}\n"
                        f"  청크 범위  : {i} ~ {i+len(batch)-1} (chunk_{i:06d} ~ chunk_{i+len(batch)-1:06d})\n"
                        f"  누적 성공  : {success_count}/{total}\n"
                        f"  경과 시간  : {elapsed:.0f}s\n"
                        f"  BATCH_SIZE : {BATCH_SIZE}\n"
                        f"  BATCH_DELAY: {BATCH_DELAY}s\n"
                        f"  에러 타입  : {error_type}\n"
                        f"  에러 내용  : {error_msg}\n"
                        f"{sep}"
                    )
                    raise
                    raise
                wait = RETRY_WAIT * attempt
                logger.warning(
                    f"  [배치 {batch_num}/{total_batches}] 실패 (시도 {attempt}/{MAX_RETRIES}) | "
                    f"청크 {i}~{i+len(batch)-1} | "
                    f"에러: {error_type} | "
                    f"{wait}초 후 재시도"
                )
                time.sleep(wait)

        if BATCH_DELAY:
            time.sleep(BATCH_DELAY)

    logger.info(
        f"Chroma upsert 완료 | "
        f"성공: {success_count} / 전체: {total} | "
        f"총 소요: {time.time() - start_time:.0f}s"
    )


def verify_collection(query: str = "authentication failure") -> None:
    """인제스트 결과 간단 검증"""
    client = PersistentClient(path=CHROMA_PATH)
    embed_fn = _get_embed_fn()
    collection = client.get_collection(COLLECTION_NAME, embedding_function=embed_fn)
    count = collection.count()
    logger.info(f"컬렉션 총 문서 수: {count}")

    results = collection.query(query_texts=[query], n_results=3)
    logger.info(f"\n검증 쿼리: '{query}'")
    for i, (doc, meta) in enumerate(
        zip(results["documents"][0], results["metadatas"][0])
    ):
        logger.info(
            f"  [{i+1}] 헤딩: {meta['heading']} | "
            f"페이지: {meta['page_start']}-{meta['page_end']}\n"
            f"      {doc[:120]}..."
        )


def main():
    parser = argparse.ArgumentParser(description="SiteMinder PDF RAG Ingest")
    parser.add_argument(
        "--pdf",
        default="./data/manuals/symantec-siteminder-12-8.pdf",
        help="PDF 파일 경로",
    )
    parser.add_argument(
        "--cache",
        default=CHUNK_CACHE_PATH,
        help="청크 캐시 JSON 경로 (기본: data/cache/siteminder_chunks.json)",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="PDF 파싱 스킵 → 캐시에서 청크 로드",
    )
    parser.add_argument(
        "--save-cache",
        action="store_true",
        help="청크 추출 후 캐시 저장 (PDF 재파싱 방지)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Chroma upsert 스킵 (검증만 실행)",
    )
    parser.add_argument(
        "--verify-query",
        default="authentication failure troubleshooting",
        help="검증용 쿼리",
    )
    args = parser.parse_args()

    if not args.skip_ingest:
        if args.use_cache:
            # ── 캐시에서 로드 ──────────────────────────────────────────
            if not Path(args.cache).exists():
                logger.error(f"캐시 파일 없음: {args.cache}  →  먼저 --save-cache로 생성하세요.")
                return
            chunks = load_chunks_cache(args.cache)
        else:
            # ── PDF 파싱 ───────────────────────────────────────────────
            if not Path(args.pdf).exists():
                logger.error(f"PDF 파일 없음: {args.pdf}")
                return
            start = time.time()
            pages = extract_pages(args.pdf)
            chunks = split_into_chunks(pages)
            logger.info(f"파싱 소요 시간: {time.time() - start:.1f}초")

            if args.save_cache:
                save_chunks_cache(chunks, args.cache)

        start = time.time()
        build_chroma_collection(chunks)
        logger.info(f"인제스트 완료. 소요 시간: {time.time() - start:.1f}초")

    verify_collection(args.verify_query)


if __name__ == "__main__":
    main()