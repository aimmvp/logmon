# src/utils/prompt_loader.py
from pathlib import Path

def load_system_context() -> str:
    path = Path(__file__).parent.parent / "prompts" / "system_context.md"
    return path.read_text(encoding="utf-8")