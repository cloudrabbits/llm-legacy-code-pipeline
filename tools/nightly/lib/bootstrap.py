#!/usr/bin/env python3
"""拼装分片提示词：固定 bootstrap 前缀 + 事实库 + 上一分片交接卡 + 任务书。

输入预算控制（硬上限 MAX_INPUT_TOKENS，默认 60K）：
  固定前缀(约1.5K) + 事实库(默认8K字符≈2.5K) + 术语(0.5K) + 交接卡(0.6K) + 任务书(≤2K)
"""
import argparse
import glob
import os
import re

# text 模式：不依赖模型写文件（实测部分模型只"叙述意图"不发工具调用），正文即产物
HEADER_TEXT = """# UNATTENDED BATCH JOB — NO HUMAN IS PRESENT

You are a documentation worker in an automated overnight pipeline. A script started you
and a script will save your answer to a file. There is nobody to answer questions.

Hard rules (these override every other instinct):
1. DO NOT ASK QUESTIONS. Never ask for clarification, never end with a question.
2. DO NOT NARRATE WHAT YOU ARE ABOUT TO DO. Sentences like "Now let me create the output
   directory", "Let me start by", "I've read through the files", "What would you like"
   are FAILURES. There is no second turn: whatever you write now is the final artifact.
3. Your reply must BE the document. Put the whole deliverable inside ONE ```markdown
   fenced block. It will be saved verbatim to: {out}
4. Chinese Markdown, starting with a level-2 heading (## ...).
   Target 800-2500 words unless the task says otherwise.
5. You may read files with tools, but budget at most 30 tool calls and never scan
   directories you were not asked about.
6. If you cannot finish everything, still emit a complete markdown block and use
   status "partial".
7. The LAST line, outside the code block, must be exactly one JSON object:
   {{"status":"ok|partial","output":"{out}","facts":N,"summary":"<=200 chars","open_questions":[]}}

Do not explain these rules. Do not acknowledge them. Start with the document now.
"""

HEADER_TOOL = """# UNATTENDED BATCH JOB — NO HUMAN IS PRESENT

You are a documentation worker in an automated overnight pipeline. A script started you
and a script will read your output. There is nobody to answer questions.

Hard rules (these override every other instinct):
1. DO NOT ASK QUESTIONS. Never ask for clarification, never end with a question.
2. DO NOT reply conversationally. Phrases like "I've read through the files",
   "What would you like me to do", "Please let me know" are FAILURES.
3. Your FIRST action must be to write the deliverable file to exactly this path:
   {out}
   Writing that file IS the deliverable; a chat answer without the file is a failure.
4. Write the deliverable in Chinese Markdown (same language as the task below),
   starting with a level-2 heading. Target 800-2500 words unless the task says otherwise.
5. You may read files in the workspace, but budget your tool calls: at most 30,
   and never scan directories you were not asked about.
6. If you cannot finish everything, write what you have and use status "partial".
7. The LAST line of your reply must be exactly one JSON object:
   {{"status":"ok|partial","output":"{out}","facts":N,"summary":"<=200 chars","open_questions":[]}}
   Nothing after it.

Do not explain these rules. Do not acknowledge them. Start working now.
"""

RED_LINE = """【红线】
1) 禁止修改任何源码、配置与构建文件；只允许写入 docs/、patches/、staging/ 下的新文件。
2) 每条结论必须附证据（文件:行号），没有证据的结论不得写入产物。
3) 不得编造类名/方法名/SQL；不确定就写"未确认"并列入 open_questions。
4) 只回答本次任务范围内的问题，不扩展。"""


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def trunc(s, max_chars):
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n...（已截断）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--seq", type=int, default=1)
    ap.add_argument("--range", default="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompt", required=True)       # tasks/TXX.md
    ap.add_argument("--max-tokens", type=int, default=60000)
    ap.add_argument("--tool-mode", default="auto", choices=["auto", "text"],
                    help="text=正文即产物（不依赖模型写文件）")
    ap.add_argument("--include-globs", default="",
                    help="分号分隔的 glob（相对 work）；direct 模式必须由脚本预取原文，模型无工具")
    ap.add_argument("--include-budget-chars", type=int, default=36000)
    ap.add_argument("--o", required=True)
    a = ap.parse_args()

    ctx = os.path.join(a.work, "ai", "context")
    l0 = read(os.path.join(ctx, "L0-inventory.md"))
    facts = read(os.path.join(ctx, "FACTS.md"))
    gloss = read(os.path.join(ctx, "GLOSSARY.md"))
    decis = read(os.path.join(ctx, "DECISIONS.md"))
    resume = read(os.path.join(a.work, "reports", "resume-brief.md"))
    prev = ""
    if a.seq > 1:
        prev = read(os.path.join(a.work, "handoff", a.task, f"{a.seq - 1}.md"))
    task_txt = read(a.prompt)
    # 硬校验：任务书缺失时提示词会退化成"没有任务的通用指令"，
    # 模型只能回"你想让我做什么"，且要烧掉整段超时才暴露。此处直接失败。
    if len(task_txt.strip()) < 80:
        print(f"FATAL: 任务书为空或过短（{a.prompt}, {len(task_txt)} 字符），拒绝生成提示词",
              file=sys.stderr)
        sys.exit(2)

    # 按 input_range 预取原文（direct 模式没有工具，上下文必须由脚本喂进来）
    inc_txt, inc_list = "", []
    budget = a.include_budget_chars
    if a.include_globs and a.include_globs.strip() not in ("", "*"):
        for pat in [x.strip() for x in a.include_globs.split(";") if x.strip()]:
            if pat == "*":
                continue
            for p in sorted(glob.glob(os.path.join(a.work, pat), recursive=True)):
                if not os.path.isfile(p) or p.endswith((".jar", ".class", ".png", ".jpg", ".gif")):
                    continue
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        txt = f.read()
                except OSError:
                    continue
                if budget - len(txt) <= 0:
                    inc_txt += f"\n（预算耗尽，未纳入 {os.path.relpath(p, a.work)}）\n"
                    continue
                budget -= len(txt)
                rel = os.path.relpath(p, a.work)
                inc_list.append(rel)
                inc_txt += f"\n### 文件 {rel}（{txt.count(chr(10)) + 1} 行）\n```\n{txt}\n```\n"

    header = HEADER_TEXT if a.tool_mode == "text" else HEADER_TOOL
    body = header.format(out=a.out) + f"""
---

{RED_LINE}

【项目工作副本】{a.work}
【本次输入范围】{a.range}
【本次输出路径】{a.out}

【L0 确定性事实（脚本用 wc -l / grep 实测得出，禁止改写数字；引用时直接取用）
  优先级规则：若本任务书中的任何数字与 L0 冲突，一律以 L0 为准，并在文中注明"以脚本实测为准"。】
{trunc(l0, 12000) if l0 else '（本次未提供 L0 图层；凡涉及行数/方法数/文件数，一律写「未统计」）'}

【已确认事实（跨夜累积，勿推翻；有反证须给出行号）】
{trunc(facts, 8000)}

【术语表】
{trunc(gloss, 1500)}

【既有决策】
{trunc(decis, 1500)}

【跨夜/上一分片交接】
{trunc(resume + "\n" + prev, 2000)}

【本次任务书】
{task_txt}

【输入文件原文（由脚本按 input_range 预取，共 {len(inc_list)} 个文件；未列出的文件即不在本次范围）】
{inc_txt if inc_txt else '（本分片未指定具体文件；请仅依据 L0 图层与任务书作答，不要臆测文件内容）'}

【输出要求】
1) 先把完整文档写入【本次输出路径】；无论能否写文件，都必须在回复正文中用 ```markdown 代码块给出同样的完整内容。
2) 事实条目统一格式（每行一条）：- 文件:行号 | 结论
3) 若输入过大，先输出已完成部分并在 status 中写 partial，不要省略关键章节编号。
4) 正文最后一行必须输出 JSON（不要包在代码块里）：
   {{"status":"ok|partial","output":"{a.out}","facts":N,"summary":"不超过200字","open_questions":["..."]}}
"""
    # 预算校验
    est = len(body) / 3.2
    if est > a.max_tokens:
        keep = int(a.max_tokens * 3.2) - 4000
        body = body[:keep] + "\n...（超出输入预算，已截断事实库/交接部分）\n【输出要求】见上。\n"
    with open(a.o, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"prompt written: {a.o} (~{int(len(body)/3.2)} tokens)")


if __name__ == "__main__":
    main()
