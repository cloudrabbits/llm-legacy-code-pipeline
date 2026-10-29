"""下载并缓存 Qwen BPE 词表，供离线 token 估算使用。

用法：
    python ops/fetch_tokenizer.py                 # 默认 Qwen2.5-32B 词表
    python ops/fetch_tokenizer.py --repo Qwen/Qwen3-32B
    python ops/fetch_tokenizer.py --check         # 只检查本地缓存是否可用

只需在外网跑一次；内网把整个 `models/qwen2_bpe/` 目录拷过去即可离线工作。
Qwen2 / Qwen3 共用同一套 151k BPE 词表。
"""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_REPO = "Qwen/Qwen2.5-32B"
DEFAULT_DEST = os.path.join("models", "qwen2_bpe", "tokenizer.json")
CANDIDATE_NAMES = ("tokenizer.json",)


def _url(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


def fetch(repo: str, dest: str, *, timeout: float = 120.0) -> str:
    """下载 tokenizer.json 到 dest，返回落盘路径。"""
    import httpx

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    url = _url(repo, CANDIDATE_NAMES[0])
    print(f"[fetch] {url} -> {dest}")
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        tmp = dest + ".part"
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
    os.replace(tmp, dest)
    size = os.path.getsize(dest)
    print(f"[fetch] ok, {size / 1e6:.1f} MB")
    return dest


def check(dest: str) -> bool:
    """检查本地缓存是否可被 tokenizers 加载；返回是否可用。"""
    if not os.path.exists(dest):
        print(f"[check] 未找到缓存: {dest}")
        return False
    try:
        from tokenizers import Tokenizer as HfTokenizer

        tok = HfTokenizer.from_file(dest)
        n = len(tok.encode("public class A { } // 中文", add_special_tokens=False).ids)
        print(f"[check] 可用：{dest}（样例 24 字符 -> {n} tokens）")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[check] 加载失败: {exc}")
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="缓存 Qwen BPE tokenizer.json")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--check", action="store_true", help="只检查本地缓存")
    args = ap.parse_args(argv)

    if args.check:
        return 0 if check(args.dest) else 1
    if os.path.exists(args.dest) and check(args.dest):
        print("[fetch] 缓存已存在，跳过下载")
        return 0
    try:
        fetch(args.repo, args.dest)
    except Exception as exc:  # noqa: BLE001
        print(f"[fetch] 失败: {exc}；将退化为启发式估算（安全系数 1.18）", file=sys.stderr)
        return 1
    return 0 if check(args.dest) else 1


if __name__ == "__main__":
    raise SystemExit(main())
