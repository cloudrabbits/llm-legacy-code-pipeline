"""项目 slug 派生的跨语言一致性。

为什么需要这个测试
------------------
同一个被分析项目的运行态落在 `runtime/<slug>/`，而这个 `<slug>` 由**三份实现**各自派生：

    pipeline/util.py               project_slug()      <- 唯一真源（Python）
    ops/watchdog.ps1             Get-ProjectSlug     <- PowerShell
    ops/deploy/linux/common.sh   _project_slug()     <- bash

它们处于三种语言、三个进程，无法共享代码。一旦规则漂移，看门狗就会去
`runtime/<另一个 slug>/state/heartbeat.json` 找心跳 —— 文件不存在或已过期，
于是它判定「心跳超时」，去杀掉并重启一个**正在正常运行**的编排器。
这类故障只有跑到半夜才会暴露，因此必须用一组固定样例把它钉死。

样例覆盖：纯英文、纯中文、中英混排、含空格、含点/连字符/下划线、含中文标点，
以及目录路径形式。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from pipeline.util import project_slug

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_SH = os.path.join(REPO_ROOT, "ops", "deploy", "linux", "common.sh")
COMMON_PS1 = os.path.join(REPO_ROOT, "ops", "deploy", "common.ps1")

# --------------------------------------------------------------------------- 期望值
#
# 注意：跨语言比对一律用 **POSIX 路径**（正斜杠）。bash 的 `basename` 不把反斜杠
# 当分隔符，喂它 `C:\a\b` 会得出错误结果；而 Linux 部署环境里项目路径本来就是
# POSIX 形式，所以这不是需要修复的差异，而是「不该这样调用」。
# Windows 反斜杠路径只在 Python 侧单独锚定（见 WINDOWS_ONLY_CASES）。

#: 参与「三方一致性」比对的样例。
#: 期望值按 Python 唯一真源的行为写死 —— 如果有人改了任一侧实现，这里就会红。
CROSS_CASES: list[tuple[str, str]] = [
    ("supermarketmanager", "supermarketmanager"),
    ("/data/supermarketmanager", "supermarketmanager"),
    ("/data/supermarketmanager/", "supermarketmanager"),
    # 非法字符（中文 / 空格 / 全角标点）按**连续段**合并成一个下划线
    ("/IdeaProjects/supermarket 商城", "supermarket_"),
    ("/IdeaProjects/我的超市", "_"),
    ("/IdeaProjects/超市(备份)", "_"),
    # 合法字符原样保留
    ("/IdeaProjects/my.project.v2", "my.project.v2"),
    ("/IdeaProjects/my-project", "my-project"),
    ("/IdeaProjects/my_project", "my_project"),
]

#: Windows 反斜杠路径：只在 Python 侧锚定（bash/PowerShell 侧不参与比对）。
WINDOWS_ONLY_CASES: list[tuple[str, str]] = [
    ("D:\\IdeaProjects\\supermarketmanager", "supermarketmanager"),
    ("D:\\IdeaProjects\\supermarketmanager\\", "supermarketmanager"),
]

#: 只在 Python 侧锚定的退化输入。
#: 这些不是「期望三方一致」的样例，而是把当前行为固化下来，防止无意中改变。
#: 空串会走到 `os.path.normpath("") == "."` 从而得到 "." —— 这是既有行为，
#: 且现实中不会发生（`--project` 必须是已存在的目录，空串更早就会被拦下）。
PYTHON_ONLY_CASES: list[tuple[str, str]] = [
    ("", "."),
    ("   ", "project"),
]


# --------------------------------------------------------------------------- 断言


def test_slug_sources_exist():
    """先确认两份跨语言实现还在原位。

    下面两个比对测试对「文件不存在 / 解释器不存在」是 skip，
    历史上 `tools/` -> `ops/` 搬移时，这两个常量没跟着改，于是比对被静默跳过、
    一致性约束形同虚设。本测试把它们钉住。
    """
    assert os.path.exists(COMMON_SH), f"缺少 bash 实现：{COMMON_SH}"
    assert os.path.exists(COMMON_PS1), f"缺少 PowerShell 实现：{COMMON_PS1}"


def test_python_slug_to_fixed_expectations():
    """锚定 Python 实现本身，期望值写死，避免「改了实现顺手改期望」。"""
    for raw, expected in CROSS_CASES + WINDOWS_ONLY_CASES + PYTHON_ONLY_CASES:
        assert project_slug(raw) == expected, f"project_slug({raw!r}) 应为 {expected!r}"


def test_bash_slug_matches_python():
    """bash 侧实现（common.sh）必须与 Python 一致。"""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("未找到 bash（Windows 未装 Git Bash / WSL），跳过 shell 侧校验")
    if not os.path.exists(COMMON_SH):
        pytest.skip(f"缺少 {COMMON_SH}")

    # 不把 common.sh 的路径交给 bash —— 本机若走 WSL（Windows 的 bash.exe），
    # 仓库的 `d:\...` 盘符路径在 Linux 侧并不存在（要挂成 `/mnt/d/...`）。
    # 直接把脚本文本喂给 stdin，绕开任何路径转换，Git Bash / WSL / Linux 都能跑。
    with open(COMMON_SH, "r", encoding="utf-8", newline="") as fh:
        # 归一化行尾：`\r` 会让 bash 把 `#!/usr/bin/env bash\r` 当成命令名而报
        # "command not found"。（.gitattributes 已强制 *.sh 为 LF，这里是双保险）
        common_src = fh.read().replace("\r\n", "\n")
    for raw, expected in CROSS_CASES:
        script = f'{common_src}\nprintf "%s" "$(_project_slug {_sh_quote(raw)})"'
        # 用二进制 stdin：Windows 下 text=True 会把 '\n' 翻译成 CRLF，
        # 导致 bash 看到 `#!/usr/bin/env bash\r` 而报 command not found。
        proc = subprocess.run(
            [bash, "-s"], input=script.encode("utf-8"), capture_output=True, timeout=30
        )
        assert proc.returncode == 0, (
            f"bash 执行失败: {proc.stderr.decode('utf-8', errors='replace')}"
        )
        actual = proc.stdout.decode("utf-8", errors="replace").strip()
        assert actual == expected, (
            f"common.sh 的 _project_slug({raw!r}) = {actual!r}，"
            f"但 pipeline/util.py 的 project_slug = {expected!r}；两边规则已漂移"
        )


def test_powershell_slug_matches_python():
    """PowerShell 侧实现（common.ps1）必须与 Python 一致。

    只 dot-source `deploy/common.ps1`，**绝不** dot-source `watchdog.ps1` ——
    后者会连带执行看门狗主体逻辑（读心跳、可能杀进程）。
    """
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("未找到 PowerShell，跳过 PS 侧校验")
    if not os.path.exists(COMMON_PS1):
        pytest.skip(f"缺少 {COMMON_PS1}")

    for raw, expected in CROSS_CASES:
        script = (
            f'. "{COMMON_PS1}"; '
            f'Get-ProjectSlug -Project {_ps_quote(raw)}'
        )
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"PowerShell 执行失败: {proc.stderr}"
        actual = proc.stdout.strip()
        assert actual == expected, (
            f"common.ps1 的 Get-ProjectSlug({raw!r}) = {actual!r}，"
            f"但 pipeline/util.py 的 project_slug = {expected!r}；两边规则已漂移"
        )


# --------------------------------------------------------------------------- 辅助


def _sh_quote(s: str) -> str:
    """单引号包裹，并按 shell 规则转义内部单引号。"""
    return "'" + s.replace("'", "'\\''") + "'"


def _ps_quote(s: str) -> str:
    """PowerShell 单引号字符串：内部单引号写成两个。"""
    return "'" + s.replace("'", "''") + "'"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
