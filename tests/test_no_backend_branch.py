"""架构约束测试：编排侧不得出现任何后端判别分支。

规格书第四节：编排器代码中不得出现 `if provider == "deepseek"` 分支，
所有后端差异收敛到 `pipeline/profiles/*` 与 `config/profiles/*.yaml`。

判定方式：用 `tokenize` 剥掉注释与字符串字面量，只检查**真正的代码**
（标识符与运算符）。文档字符串里提到后端名是允许的——那正是说明
「差异已收敛到哪里」的地方；但代码里出现后端名就意味着存在分支。
"""

from __future__ import annotations

import io
import os
import tokenize

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 编排侧源码（profiles/ 包是唯一的后端差异收敛点，不在扫描范围内）
#:
#: ★ 这里是**硬约束**：一旦某个文件被重命名/移动而没有同步本清单，测试会
#: **失败**而不是跳过——历史上 `pipeline/stages.py` 拆成 `pipeline/stages/`
#: 包后，本清单仍写着旧路径，而当时的逻辑是 `pytest.skip`，于是 677 行的阶段
#: 代码在无人察觉的情况下脱离了「禁止后端判别分支」的约束检查。
SCANNED = [
    "pipeline/backend.py",
    "pipeline/executor.py",
    "pipeline/models.py",
    "pipeline/errors.py",
    "pipeline/tokenizer.py",
    "pipeline/util.py",
    "pipeline/transports.py",
    "pipeline/config_loader.py",
    "orchestrator.py",
    "pipeline/context.py",
    "pipeline/session.py",
    "pipeline/planner.py",
    "pipeline/checkpoint.py",
    "pipeline/artifacts.py",
    "pipeline/monitor.py",
    "pipeline/scan.py",
    "pipeline/acceptance.py",
    "pipeline/logging_setup.py",
    # stages 由单个 stages.py 拆成的包：每个模块都要纳入扫描
    "pipeline/stages/__init__.py",
    "pipeline/stages/common.py",
    "pipeline/stages/p0_baseline.py",
    "pipeline/stages/p1_classify.py",
    "pipeline/stages/p2_modules.py",
    "pipeline/stages/p3_deps.py",
    "pipeline/stages/p4_architecture.py",
    "pipeline/stages/p5_report.py",
]

FORBIDDEN = ["deepseek", "ollama", "qwen3", "provider"]


def code_only(source: str) -> str:
    """去掉注释与字符串字面量，只保留代码骨架（小写）。"""
    kept: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(tok.string)
    return " ".join(kept).lower()


@pytest.mark.parametrize("rel_path", SCANNED)
def test_no_backend_specific_branch(rel_path: str):
    path = os.path.join(REPO_ROOT, rel_path)
    if not os.path.exists(path):
        # 不跳过：文件缺失几乎总是「重命名/移动后忘了同步 SCANNED」，
        # 静默跳过会让该文件在无人知晓的情况下脱离架构约束。
        pytest.fail(
            f"架构约束扫描目标不存在：{rel_path}。"
            f"若该文件已被重命名或移动，请同步更新本文件的 SCANNED 清单。"
        )
    with open(path, "r", encoding="utf-8") as fh:
        code = code_only(fh.read())
    for token in FORBIDDEN:
        assert token not in code, f"{rel_path} 的代码里出现后端专属标识 {token!r}；后端差异必须收敛到 profiles/"


def test_profiles_package_is_the_only_place_with_backend_names():
    """反向确认：后端名只允许出现在 profiles 包、config 与运维脚本里。"""
    allowed_prefixes = (
        os.path.join(REPO_ROOT, "pipeline", "profiles"),
        os.path.join(REPO_ROOT, "config"),
        os.path.join(REPO_ROOT, "contract_tests"),
        os.path.join(REPO_ROOT, "tests"),
        os.path.join(REPO_ROOT, "ops"),    # 运维脚本（profile 名/厂商词是合法输入）
        os.path.join(REPO_ROOT, "jlp"),    # 静态事实层（只读解析，与后端无关）
    )
    offenders = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {".git", "__pycache__", ".pytest_cache", "out", "runtime", "logs", "models", ".venv"}
        ]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            if any(full.startswith(p) for p in allowed_prefixes):
                continue
            with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                code = code_only(fh.read())
            hit = [t for t in FORBIDDEN if t in code]
            if hit:
                offenders.append(f"{os.path.relpath(full, REPO_ROOT)}:{hit}")
    assert not offenders, f"后端名出现在非收敛位置: {offenders}"
