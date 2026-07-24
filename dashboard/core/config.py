"""設定(パス・レート・プラン)の読み込み。

レートは**コードに埋めない**(変動/一部非公開)。``config/rates.toml`` があれば
それを、無ければ ``config/rates.example.toml`` を読む。example のプレースホルダ
レート(全 0)を使っているときは、コストが参考にならない事実を UI で警告できるよう
``rates_are_placeholder`` を立てる。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = DASHBOARD_DIR / "config"


@dataclass(frozen=True)
class Plan:
    name: str
    price: float
    included: Optional[int] = None


@dataclass(frozen=True)
class Rates:
    input: float
    output: float
    orchestration_input: float
    orchestration_output: float

    @property
    def all_zero(self) -> bool:
        return (
            self.input == 0
            and self.output == 0
            and self.orchestration_input == 0
            and self.orchestration_output == 0
        )


@dataclass(frozen=True)
class Settings:
    live_path: str
    sample_path: str
    rates: Rates
    plans: tuple[Plan, ...] = field(default_factory=tuple)
    source_file: str = ""
    rates_are_placeholder: bool = False

    def resolve(self, path_str: str) -> str:
        """dashboard/ 基準の相対パスを絶対パスに解決する。

        設定内のパス(例 ``../sample-data/...``)は dashboard ディレクトリからの
        相対で書く(PROMPT の既定 ``../chat/data/usage.jsonl`` に合わせる)。
        """
        p = Path(path_str)
        if p.is_absolute():
            return str(p)
        return str((DASHBOARD_DIR / p).resolve())


def _load_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_settings() -> Settings:
    """rates.toml を優先し、無ければ rates.example.toml を読む。"""
    real = CONFIG_DIR / "rates.toml"
    example = CONFIG_DIR / "rates.example.toml"
    path = real if real.exists() else example
    data = _load_toml(path)

    source = data.get("source", {})
    rates_raw = data.get("rates", {})
    rates = Rates(
        input=float(rates_raw.get("input", 0.0)),
        output=float(rates_raw.get("output", 0.0)),
        orchestration_input=float(rates_raw.get("orchestration_input", 0.0)),
        orchestration_output=float(rates_raw.get("orchestration_output", 0.0)),
    )
    plans = tuple(
        Plan(name=p["name"], price=float(p["price"]), included=p.get("included"))
        for p in data.get("plans", [])
    )

    return Settings(
        live_path=source.get("live_path", "../chat/data/usage.jsonl"),
        sample_path=source.get("sample_path", "../sample-data/usage.sample.jsonl"),
        rates=rates,
        plans=plans,
        source_file=path.name,
        rates_are_placeholder=rates.all_zero,
    )
