"""pytest 共通設定。scripts/ を import path に載せ、テスト用 DB を分離する。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """db.DB_PATH を一時ファイルに差し替えて初期化済み接続環境を返す。"""
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "race.db")
    db.init_db()
    return db


@pytest.fixture
def fixture_html():
    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load
