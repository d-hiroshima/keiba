"""`.claude/agents/*.md` の system prompt を読み込む共通ロジック。

設計のキモ: A（Claude Code）と B（Slack bot）でプロンプトを一元管理する。
A 側で改善したエージェント定義は、Slack bot を再起動 / 再デプロイすれば B に反映される。

各 agent ファイルは YAML フロントマター付き Markdown:

  ---
  name: pedigree-analyst
  description: ...
  tools: Read, Grep, Glob, Bash, WebFetch
  ---

  あなたは...

このうち YAML フロントマター以下の本文を system prompt として返す。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "agents"


def _agent_dir() -> Path:
    return Path(os.environ.get("KEIBA_AGENT_PROMPTS_DIR", DEFAULT_PROMPTS_DIR))


def load_agent(name: str) -> dict[str, Any]:
    """指定エージェントの system prompt と meta を読み込んで返す。

    name は agents ディレクトリ内のファイル名（拡張子なし）に一致する。
    例: "pedigree-analyst" → `.claude/agents/pedigree-analyst.md`

    返り値:
        {
            "name": "pedigree-analyst",
            "description": "...",
            "tools": ["Read", "Grep", ...],
            "system_prompt": "あなたは...（フロントマター以下の本文）",
        }
    """
    path = _agent_dir() / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"agent prompt not found: {path}")

    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    return {
        "name": meta.get("name", name),
        "description": meta.get("description", ""),
        "tools": [t.strip() for t in meta.get("tools", "").split(",") if t.strip()],
        "system_prompt": body.strip(),
    }


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """軽量な YAML フロントマターパーサ（依存追加を避けるため自前）。

    対応するのは `key: value` 形式のフラットな YAML のみ。
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    fm_block = text[4:end]
    body = text[end + 5:]

    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, body


def load_all() -> dict[str, dict[str, Any]]:
    """全エージェントを名前 → meta dict のマップで返す。"""
    return {p.stem: load_agent(p.stem) for p in _agent_dir().glob("*.md")}


if __name__ == "__main__":
    for name, meta in load_all().items():
        print(f"[{name}] {meta['description'][:80]}...")
