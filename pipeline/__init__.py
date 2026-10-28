"""夜间无人值守分析流水线。

设计约束（来自规格书第四节）：
    编排器代码中不得出现 `if provider == "deepseek"` 之类的后端分支。
    所有后端差异收敛到 `pipeline/profiles/*.py` + `config/profiles/*.yaml`，
    切换后端 = 改 `--profile` 参数。
"""

__version__ = "0.1.0"
