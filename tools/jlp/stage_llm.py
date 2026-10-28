"""阶段 5（可选）：LLM 叙述增强。

**默认关闭**。前三份文档已经完整可读；本阶段只是让模型把冷冰冰的表格
改写成连贯的段落，便于非技术干系人阅读。

约束（沿用 nightly 阶段的实测结论）：
  * 提示词里只喂**脚本算好的事实**，明确禁止模型改动任何数字；
  * `think=false`，避免思考 token 吃掉输出预算；
  * 服务不可达时直接跳过并降级，不影响前面阶段的产物。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import lib_md as md

SYSTEM = (
    "你是资深 Java Web 架构师，正在为一个遗留 JSP 项目编写需求分析文档的叙述段落。\n"
    "硬性规则：\n"
    "1. 只能使用【事实】中出现的信息，不得新增、修改或推测任何数字、文件名、类名；\n"
    "2. 不要输出任何代码，不要输出表格，只输出 Markdown 正文段落；\n"
    "3. 用中文，语气客观，避免形容词堆砌；\n"
    "4. 不要复述事实原文，而是解释它们之间的**关系与含义**。\n"
)

PROMPTS = [
    ("project_charter", "项目定位与干系人",
     "说明这个系统解决什么问题、面向谁使用、在系统边界上做了什么、没做什么。"),
    ("module_walkthrough", "模块关系与业务流程",
     "按模块清单，说明各模块之间的业务关系与典型操作路径。"),
    ("risk_commentary", "风险解读与整改次序",
     "对风险清单按「影响面 × 修复成本」排序，说明为什么这个次序最划算。"),
]


def _call(api: str, model: str, prompt: str, timeout: int, num_predict: int = 1200) -> str:
    payload = json.dumps({
        "model": model, "prompt": SYSTEM + "\n【事实】\n" + prompt,
        "stream": False, "think": False,
        "options": {"temperature": 0.2, "num_predict": num_predict},
    }).encode("utf-8")
    req = urllib.request.Request(api, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    return (body.get("response") or "").strip()


def run(ctx, api: str, model: str, timeout: int = 300) -> str | None:
    proj = ctx["project"]
    modules = ctx["derived"].get("modules", [])
    risks = ctx["derived"].get("risks", [])
    tech = ctx["tech"]

    facts = {
        "project": proj["name"],
        "arch": tech["arch"],
        "counts": {"java": len(proj["java"]), "jsp": len(proj["jsp"])},
        "tech_stack": [{"dim": r[0], "value": r[1]} for r in tech["rows"]],
        "modules": [{"domain": m["domain"], "pages": m["pages"],
                     "competences": m["competences"], "tables": m["tables"],
                     "actions": m["actions"]} for m in modules],
        "risks": [{"level": r["level"], "title": r["title"], "detail": r["detail"]}
                  for r in risks],
    }
    blob = json.dumps(facts, ensure_ascii=False, indent=1)
    if len(blob) > 12000:  # 事实太多时截断，保住模型上下文预算
        blob = blob[:12000] + "\n...(事实已截断)"

    out = [md.h(1, "05 · LLM 叙述增强（可选产物）")]
    out.append(f"> 模型 `{model}` @ `{api}`\n")

    ok = 0
    for key, title, task in PROMPTS:
        prompt = f"# 本次任务\n{task}\n\n{blob}\n"
        try:
            text = _call(api, model, prompt, timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
            out.append(md.h(2, title))
            out.append(f"*跳过：模型服务不可达（`{type(e).__name__}: {e}`）。*\n")
            continue
        out.append(md.h(2, title))
        out.append((text or "（模型返回空）") + "\n")
        ok += 1

    path = os.path.join(ctx["out"], "05-llm-narrative.md")
    md.write_atomic(path, "\n".join(out))
    ctx["llm_state"] = f"已启用（{ok}/{len(PROMPTS)} 段生成成功，模型 {model}）" if ok else \
        "尝试启用但模型不可达，产物为纯静态事实"
    return path
