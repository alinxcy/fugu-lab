"""Config Loader — エンドポイント/モデル/鍵/レートを外出しで読む。

設定の優先順位:
  1. 環境変数 FUGU_CHAT_CONFIG が指すパス
  2. config/endpoints.json (実運用。.gitignore 済み)
  3. config/endpoints.example.json (雛形。無ければこれで動く)

API キーはコードにも設定ファイルにも埋めない。設定の api_key_env が示す環境変数から
読む(.env は python-dotenv で読み込む)。鍵はサーバー側にのみ保持しブラウザに渡さない。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

CHAT_DIR = Path(__file__).resolve().parent.parent  # .../chat
CONFIG_DIR = CHAT_DIR / "config"


class ConfigError(Exception):
    pass


def _resolve_config_path() -> Path:
    env_path = os.environ.get("FUGU_CHAT_CONFIG")
    if env_path:
        return Path(env_path)
    real = CONFIG_DIR / "endpoints.json"
    if real.exists():
        return real
    return CONFIG_DIR / "endpoints.example.json"


class Config:
    def __init__(self, data: dict[str, Any], source: Path) -> None:
        self._data = data
        self.source = source

    @property
    def default_provider(self) -> str:
        return self._data.get("default_provider", "fugu")

    @property
    def default_model(self) -> Optional[str]:
        return self._data.get("default_model")

    @property
    def system_prompt_presets(self) -> dict[str, str]:
        return self._data.get("system_prompt_presets", {})

    def _abs(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (CHAT_DIR / path)

    @property
    def usage_log_path(self) -> Path:
        return self._abs(self._data.get("usage_log_path", "data/usage.jsonl"))

    @property
    def raw_log_path(self) -> Path:
        return self._abs(self._data.get("raw_log_path", "data/raw.jsonl"))

    def provider_config(self, name: str) -> dict[str, Any]:
        providers = self._data.get("providers", {})
        if name not in providers:
            raise ConfigError(f"provider '{name}' が設定にありません: {self.source}")
        return providers[name]

    def resolve_api_key(self, provider_name: str) -> Optional[str]:
        pc = self.provider_config(provider_name)
        env_name = pc.get("api_key_env")
        if not env_name:
            return None  # 認証不要のプロバイダ(例: LM Studio)を将来許容するため None 可
        return os.environ.get(env_name)

    def public_view(self) -> dict[str, Any]:
        """ブラウザに渡してよい範囲だけ(鍵は絶対に含めない)。"""
        providers = {}
        for name, pc in self._data.get("providers", {}).items():
            providers[name] = {
                "adapter": pc.get("adapter"),
                "default_model": pc.get("default_model"),
                "models": pc.get("models", []),
            }
        return {
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "system_prompt_presets": self.system_prompt_presets,
            "providers": providers,
        }


def load_config() -> Config:
    load_dotenv(CHAT_DIR / ".env")  # あれば読む。無くても環境変数が使えれば動く。
    path = _resolve_config_path()
    if not path.exists():
        raise ConfigError(f"設定ファイルが見つかりません: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Config(data, path)
