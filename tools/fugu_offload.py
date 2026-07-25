#!/usr/bin/env python3
"""fugu_offload — Claude(実装エージェント)が機械的な下請けを Fugu base に外注するための CLI。

方針は docs/claude-fugu-offload.md:
  「生成が重く・検証が軽い」タスクだけを base fugu に投げ、出力は必ずサニタイズしてから使う。

設計上の肝: 既定で **chat アプリ経由**(http://127.0.0.1:PORT/api/chat)で叩く。
そうすると外注 1 回ごとに UsageRecord が JSONL に追記され、**作業がそのまま測定データになる**。
アプリが起動していなければ直接 API にフォールバックする(この場合は記録されない旨を警告)。

使い方:
    python tools/fugu_offload.py --task code     --prompt "関数 slugify(s) を書け"
    python tools/fugu_offload.py --task json     --prompt "この文から {name, price} を抽出: ..."
    python tools/fugu_offload.py --task regex    --prompt "日本の郵便番号にマッチする正規表現"
    python tools/fugu_offload.py --task translate --prompt "この API は裏で複数モデルを協調させる"
    python tools/fugu_offload.py --task summary  --prompt "次を1文で要約: ..."
    echo "長い原文" | python tools/fugu_offload.py --task summary --stdin

標準出力にはサニタイズ済みの成果物だけを出す(パイプで繋げる)。実測値は stderr。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Optional

import httpx

APP_URL = os.environ.get("FUGU_CHAT_URL", "http://127.0.0.1:8150")
DIRECT_URL = "https://api.sakana.ai/v1/chat/completions"

# タスク種別ごとの「出力形式を縛る」指示。base fugu は放っておくと
# 「Sakana AI が開発した…」等の前置きを付けるため、明示的に抑える。
TASK_PREFIX = {
    "code": "コードのみを出力せよ。説明・前置き・後書きは一切不要。",
    "json": "有効な JSON のみを出力せよ。説明・前置き・コードフェンス以外の文字は一切不要。",
    "regex": "正規表現パターン文字列のみを1行で出力せよ。説明・コード・前置きは不要。",
    "translate": "訳文のみを出力せよ。原文の再掲・説明・前置きは不要。",
    "summary": "要約のみを出力せよ。前置き・見出し・箇条書きの装飾は不要。",
    "raw": "",
}

# 思考過程(CoT)が最終出力に漏れることがあるため、機械処理前に落とす。
COT_MARKERS = [
    r"^\s*(Wait|Let me|Let's|Hmm|Actually|First,? I|I should|I need to)\b.*$",
    r"^\s*\*?Wait\b.*$",
]


def build_prompt(task: str, user_prompt: str) -> str:
    prefix = TASK_PREFIX.get(task, "")
    return f"{prefix}\n\n{user_prompt}".strip() if prefix else user_prompt


def build_params(model: str, max_tokens: int, effort: Optional[str] = None) -> dict[str, Any]:
    """provider に素通しするパラメータ。

    `reasoning.effort`(high/xhigh/max)は **明示指定したときだけ** 送る。
    予備実験(docs/fugu-findings.md §5.6 実験C)では ultra で high が既定より
    安く・速い傾向が出たが、**n=2・単一タスクのみで未確定**。既定値としては採用しない。
    base fugu では effort は無効(実測)。
    """
    params: dict[str, Any] = {"max_tokens": max_tokens}
    if effort:
        params["reasoning"] = {"effort": effort}
    return params


def call_via_app(prompt: str, model: str, max_tokens: int, timeout: float,
                 effort: Optional[str] = None) -> tuple[str, dict]:
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "params": build_params(model, max_tokens, effort),
    }
    content = ""
    measured: dict[str, Any] = {}
    with httpx.stream("POST", f"{APP_URL}/api/chat", json=body, timeout=timeout) as r:
        r.raise_for_status()
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                for line in raw.split("\n"):
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:].strip())
                    if ev.get("type") == "delta":
                        content += ev.get("content", "")
                    elif ev.get("type") == "done":
                        measured = ev.get("measured") or {}
                        if ev.get("content"):
                            content = ev["content"]
                    elif ev.get("type") == "error":
                        raise RuntimeError(ev.get("error", "provider error"))
    return content, measured


def call_direct(prompt: str, model: str, max_tokens: int, timeout: float,
                effort: Optional[str] = None) -> tuple[str, dict]:
    key = os.environ.get("FUGU_API_KEY")
    if not key:
        # chat/.env から拾う(リポジトリ内の運用に合わせる)
        env_path = os.path.join(os.path.dirname(__file__), "..", "chat", ".env")
        if os.path.exists(env_path):
            for line in open(env_path, encoding="utf-8"):
                if line.startswith("FUGU_API_KEY="):
                    key = line.strip().split("=", 1)[1]
    if not key:
        raise RuntimeError("FUGU_API_KEY が見つかりません(.env か環境変数に設定してください)")
    r = httpx.post(
        DIRECT_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              **build_params(model, max_tokens, effort)},
        timeout=timeout,
    )
    d = r.json()
    if "error" in d:
        raise RuntimeError(d["error"].get("message", "provider error"))
    u = d.get("usage", {}) or {}
    pd = u.get("prompt_tokens_details", {}) or {}
    cd = u.get("completion_tokens_details", {}) or {}
    orch_i = pd.get("orchestration_input_tokens")
    orch_o = cd.get("orchestration_output_tokens")
    vis = (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
    orch = (orch_i or 0) + (orch_o or 0) if orch_i is not None else None
    measured = {
        "visible_tokens": vis,
        "orchestration_tokens": orch,
        "orchestration_ratio": (orch / (vis + orch)) if orch is not None and (vis + orch) else None,
    }
    return d["choices"][0]["message"]["content"], measured


def strip_cot(text: str) -> str:
    """内部思考の漏れらしき行を落とす。"""
    out = []
    for line in text.splitlines():
        if any(re.match(p, line, re.I) for p in COT_MARKERS):
            continue
        out.append(line)
    return "\n".join(out)


def sanitize(task: str, text: str) -> str:
    """タスク種別ごとに成果物だけを取り出す。前置き・CoT・フェンスを除去。"""
    text = strip_cot(text).strip()

    if task == "code":
        m = re.search(r"```(?:[a-zA-Z0-9_+-]*)\s*\n(.*?)```", text, re.S)
        return (m.group(1) if m else text).strip()

    if task == "json":
        m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.S)
        if m:
            text = m.group(1).strip()
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)  # 前後の散文を捨てる
        return (m.group(1) if m else text).strip()

    if task == "regex":
        line = [l for l in text.splitlines() if l.strip()]
        pat = line[-1].strip() if line else text.strip()
        pat = pat.strip("`").strip()
        return re.sub(r'^r?["\']|["\']$', "", pat)

    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Fugu base への外注 CLI(出力はサニタイズ済み)")
    ap.add_argument("--task", default="raw", choices=sorted(TASK_PREFIX), help="タスク種別(出力形式の縛りとサニタイズ方法を決める)")
    ap.add_argument("--prompt", default="", help="依頼内容")
    ap.add_argument("--stdin", action="store_true", help="標準入力を prompt の末尾に付ける")
    ap.add_argument("--model", default="fugu", help="既定 fugu(base)。ultra は外注に不向き")
    ap.add_argument("--max-tokens", type=int, default=2000, help="reasoning が枠を食うので余裕を持つ")
    ap.add_argument("--effort", choices=["high", "xhigh", "max"], default=None,
                    help="reasoning.effort を明示指定(未指定ならプロバイダ既定)。効果は未確定なので実験時のみ")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--raw-output", action="store_true", help="サニタイズせず生出力を出す")
    args = ap.parse_args()

    user_prompt = args.prompt
    if args.stdin or not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            user_prompt = f"{user_prompt}\n\n{piped}".strip()
    if not user_prompt:
        ap.error("--prompt か標準入力で依頼内容を渡してください")

    prompt = build_prompt(args.task, user_prompt)

    via = "app"
    try:
        content, measured = call_via_app(prompt, args.model, args.max_tokens, args.timeout, args.effort)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] chat アプリ経由に失敗({e})。直接 API にフォールバックします "
              f"— この呼び出しは JSONL に記録されません。", file=sys.stderr)
        via = "direct"
        content, measured = call_direct(prompt, args.model, args.max_tokens, args.timeout, args.effort)

    result = content if args.raw_output else sanitize(args.task, content)

    ratio = measured.get("orchestration_ratio")
    el = measured.get("elapsed_s")
    print(
        f"[fugu_offload] via={via} model={args.model} task={args.task} "
        f"elapsed={round(el,1) if isinstance(el,(int,float)) else '-'}s "
        f"表={measured.get('visible_tokens')} 裏={measured.get('orchestration_tokens')} "
        f"裏率={round(ratio*100) if ratio is not None else '-'}%",
        file=sys.stderr,
    )
    if not result.strip():
        print("[warn] 出力が空です。max_tokens を増やすか task=raw で生出力を確認してください。", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
