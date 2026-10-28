#!/usr/bin/env python3
"""跨夜编排状态库封装（SQLite）。

设计要点：
  * 产物先原子落盘、校验通过后才写 done（避免"幽灵进度"）
  * 分片（chunk）是续跑的真正粒度
  * fact 表按 pk upsert，天然幂等
  * file_snap 按 night_id 存快照，用于白天变更失效判定
"""
import argparse
import fnmatch
import hashlib
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMA = os.path.join(os.path.dirname(HERE), "db", "schema.sql")


def conn(db):
    c = sqlite3.connect(db, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _now():
    return int(time.time())


# ---------------------------------------------------------------- 初始化
def cmd_init(a):
    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    with open(a.schema) as f:
        sql = f.read()
    c = conn(a.db)
    c.executescript(sql)
    # 轻量迁移：老库缺列时补上（SQLite 无 ADD COLUMN IF NOT EXISTS）
    for tbl, col, typ in (("chunk", "last_error", "TEXT"),
                          ("task", "max_out", "INTEGER DEFAULT 0")):
        cols = {r[1] for r in c.execute("PRAGMA table_info(%s)" % tbl)}
        if col not in cols:
            c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, typ))
    c.commit()
    print("db initialized:", a.db)


def _int_or_none(v):
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _parse_chunks(taskdir, task_id, chunks_file, output):
    """返回 [(seq, input_range, output_part)]。无分片文件时退化为单分片。

    分片文件列分隔符支持制表符或 |；路径允许写成 `tasks/xxx` 或直接 `xxx`。
    """
    if chunks_file and chunks_file != "-":
        cand = [chunks_file]
        if not os.path.isabs(chunks_file):
            cand = [os.path.join(taskdir, os.path.basename(chunks_file)),
                    os.path.join(taskdir, chunks_file), chunks_file]
        path = next((p for p in cand if os.path.exists(p)), None)
        if path is None:
            print(f"WARN: 分片文件不存在 {chunks_file}（任务 {task_id} 退化为单分片）", file=sys.stderr)
            return [(1, "*", output)]
        rows = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sep = "\t" if "\t" in line else "|"
                parts = [p.strip() for p in line.split(sep)]
                if len(parts) < 3:
                    continue
                rows.append((int(parts[0]), parts[1], parts[2]))
        return rows or [(1, "*", output)]
    return [(1, "*", output)]


def cmd_load_queue(a):
    c = conn(a.db)
    if a.fresh:
        c.execute("DELETE FROM chunk")
        c.execute("DELETE FROM task")
    n_task = n_chunk = 0
    with open(a.queue) as f:
        header = None
        for line in f:
            line = line.replace("\r", "").rstrip("\n")   # 兼容 CRLF
            if not line.strip() or line.startswith("#"):
                continue
            cols = [x.strip() for x in line.split("\t")]
            if header is None:
                header = cols
                continue
            row = dict(zip(header, cols))
            tid = row["id"]
            # 已存在的任务也要刷新"元数据"（任务书路径/验收规则/超时/优先级），
            # 否则改了 queue.tsv 却不生效，只能 --fresh（会丢掉全部进度）。
            # 只保留 status / attempt / 时间戳，不覆盖运行态。
            c.execute(
                """UPDATE task SET phase=?, title=?, prompt=?, depends=?, output=?, chunks_file=?,
                          priority=?, timeout_min=?, retries=?, check_rule=?,
                          max_out=COALESCE(?, max_out)
                   WHERE id=?""",
                (row.get("phase", ""), row.get("title", ""), row.get("prompt", ""),
                 row.get("depends", "-"), row.get("output", ""), row.get("chunks", "-"),
                 int(row.get("priority", 5) or 5), int(row.get("timeout_min", 25) or 25),
                 int(row.get("retries", 2) or 2), row.get("check", ""),
                 _int_or_none(row.get("max_out")), tid),
            )
            # 同步分片表：next-chunk 取的是 chunk.output_part（建表时写入），
            # 若只改 task.output，已存在的分片仍会用旧输出路径（实测 T16 踩到）。
            # 仅对单分片任务整体覆盖；分片任务的 .part 路径来自 chunks 文件，另行处理。
            c.execute(
                """UPDATE chunk SET output_part=?
                   WHERE task_id=? AND (SELECT COUNT(*) FROM chunk c2 WHERE c2.task_id=?) = 1""",
                (row.get("output", ""), tid, tid),
            )
            # 仅新任务插入；已存在的走上面的 UPDATE，绝不覆盖 status/attempt
            c.execute(
                """INSERT INTO task
                   (id,phase,title,prompt,depends,output,chunks_file,priority,timeout_min,retries,check_rule,max_out,status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending')
                   ON CONFLICT(id) DO NOTHING""",
                (
                    tid, row.get("phase", ""), row.get("title", ""), row.get("prompt", ""),
                    row.get("depends", "-"), row.get("output", ""), row.get("chunks", "-"),
                    int(row.get("priority", 5) or 5), int(row.get("timeout_min", 25) or 25),
                    int(row.get("retries", 2) or 2), row.get("check", ""),
                    _int_or_none(row.get("max_out")) or 0,
                ),
            )
            n_task += 1
            for seq, rng, out in _parse_chunks(a.taskdir, tid, row.get("chunks", "-"), row.get("output", "")):
                cid = f"{tid}#{seq}"
                if c.execute("SELECT 1 FROM chunk WHERE id=?", (cid,)).fetchone():
                    continue
                c.execute(
                    "INSERT INTO chunk (id,task_id,seq,input_range,output_part) VALUES (?,?,?,?,?)",
                    (cid, tid, seq, rng, out),
                )
                n_chunk += 1
    c.commit()
    print(f"loaded tasks={n_task} chunks={n_chunk}")


# ---------------------------------------------------------------- 调度
def _dep_ok(c, depends, dropped_ok=("done", "dropped")):
    if not depends or depends == "-":
        return True
    for d in [x.strip() for x in depends.split(",") if x.strip()]:
        r = c.execute("SELECT status FROM task WHERE id=?", (d,)).fetchone()
        if not r or r["status"] not in dropped_ok:
            return False
    return True


def cmd_next_chunk(a):
    """选下一个可执行分片：stale 优先 → priority → task.id → seq"""
    exclude = set()
    if a.exclude_file and os.path.exists(a.exclude_file):
        with open(a.exclude_file) as f:
            exclude = {x.strip() for x in f if x.strip()}
    c = conn(a.db)
    rows = c.execute(
        """SELECT k.*, t.title, t.phase, t.prompt, t.depends, t.timeout_min, t.retries, t.check_rule,
                  t.priority, t.max_out
           FROM chunk k JOIN task t ON t.id=k.task_id
           WHERE k.status IN ('pending','stale')
             AND t.status IN ('pending','partial','stale','failed')
           ORDER BY (CASE k.status WHEN 'stale' THEN 0 ELSE 1 END),
                    t.priority, t.id, k.seq"""
    ).fetchall()
    for r in rows:
        if r["id"] in exclude:
            continue
        if a.only_task and r["task_id"] != a.only_task:
            continue
        if r["attempt"] >= r["retries"] and r["status"] != "stale":
            continue
        if not a.no_dep and not _dep_ok(c, r["depends"]):
            continue
        print("\t".join([
            r["id"], r["task_id"], str(r["seq"]), r["input_range"] or "*",
            r["output_part"] or "", r["prompt"] or "", str(r["timeout_min"]),
            r["check_rule"] or "", r["title"] or "", r["phase"] or "",
            str(r["max_out"] or 0),
        ]))
        return 0
    return 1


def cmd_chunk_start(a):
    c = conn(a.db)
    c.execute("UPDATE chunk SET status='running', attempt=attempt+1, night_id=? WHERE id=?", (a.night, a.id))
    c.execute("UPDATE task SET status='running', attempt=attempt+1, night_id=?, started_at=? WHERE id=?",
              (a.night, _now(), a.id.split("#")[0]))
    c.commit()


def cmd_chunk_done(a):
    c = conn(a.db)
    c.execute("UPDATE chunk SET status='done', night_id=?, chars_out=?, seconds=?, handoff=? WHERE id=?",
              (a.night, a.chars, a.seconds, a.handoff, a.id))
    tid = a.id.split("#")[0]
    left = c.execute("SELECT COUNT(*) n FROM chunk WHERE task_id=? AND status<>'done'", (tid,)).fetchone()["n"]
    if left == 0:
        c.execute("UPDATE task SET status='done', night_id=?, finished_at=? WHERE id=?", (a.night, _now(), tid))
    else:
        c.execute("UPDATE task SET status='partial', night_id=? WHERE id=?", (a.night, tid))
    c.commit()


def cmd_chunk_fail(a):
    c = conn(a.db)
    r = c.execute("SELECT * FROM chunk WHERE id=?", (a.id,)).fetchone()
    t = c.execute("SELECT retries FROM task WHERE id=?", (r["task_id"],)).fetchone()
    if r["attempt"] < t["retries"]:
        c.execute("UPDATE chunk SET status='pending', last_error=NULL WHERE id=?", (a.id,))
        st = "partial"
    else:
        c.execute("UPDATE chunk SET status='failed' WHERE id=?", (a.id,))
        st = "failed"
    c.execute("UPDATE chunk SET handoff=? WHERE id=?", (a.error[:500], a.id))
    c.execute("UPDATE task SET status=?, last_error=? WHERE id=?", (st, a.error[:500], r["task_id"]))
    c.commit()


def cmd_reset_running(a):
    """启动期修复：昨晚 running/partial 回退，避免卡死状态"""
    c = conn(a.db)
    c.execute("UPDATE chunk SET status='pending' WHERE status='running'")
    c.execute("UPDATE task SET status='pending' WHERE status='running'")
    c.commit()
    print("reset running -> pending")


def cmd_ghosts(a):
    """幽灵进度：标记 done 但产物缺失/为空"""
    c = conn(a.db)
    bad = []
    for r in c.execute("SELECT id, output_part FROM chunk WHERE status='done'"):
        p = os.path.join(a.work, r["output_part"] or "")
        if not r["output_part"] or (not os.path.exists(p)) or os.path.getsize(p) == 0:
            bad.append(r["id"])
            c.execute("UPDATE chunk SET status='pending' WHERE id=?", (r["id"],))
    for cid in bad:
        c.execute("UPDATE task SET status='pending' WHERE id=?", (cid.split("#")[0],))
    c.commit()
    print(json.dumps({"ghosts": bad}))


# ---------------------------------------------------------------- 事实库
def cmd_fact_upsert(a):
    c = conn(a.db)
    c.execute(
        """INSERT INTO fact (pk,claim,evidence,task_id,night_id,confidence,created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(pk) DO UPDATE SET claim=excluded.claim, evidence=excluded.evidence,
             task_id=excluded.task_id, night_id=excluded.night_id, confidence=excluded.confidence""",
        (a.pk, a.claim, a.evidence, a.task, a.night, a.confidence, _now()),
    )
    c.commit()


def cmd_fact_export(a):
    c = conn(a.db)
    rows = c.execute("SELECT * FROM fact ORDER BY task_id, pk").fetchall()
    lines = ["# 已确认事实（跨夜累积，脚本渲染）", ""]
    size = 0
    for r in rows:
        line = f"- {r['evidence']} | {r['claim']}  `({r['task_id']}/N{r['night_id']}/{r['confidence']})`"
        if size + len(line) > a.max_chars:
            lines.append(f"- ...（截断，共 {len(rows)} 条，注入上限 {a.max_chars} 字符）")
            break
        lines.append(line)
        size += len(line)
    with open(a.file, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"facts exported: {len(rows)} -> {a.file}")


# ---------------------------------------------------------------- 快照 / 失效
SRC_PATTERNS = (".java", ".jsp", ".sql", ".xml", ".properties", ".tld")
# 生成物与工具目录不进快照：否则每夜都会误判为"源码变更"，触发全量失效重算
EXCLUDE_DIRS = {".git", ".svn", "target", "build", "node_modules", "assets",
                "docs", "reports", "patches", "staging", "ai", "handoff", "tools"}


def _iter_source(src):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if fn.endswith(SRC_PATTERNS):
                yield os.path.join(root, fn)


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def cmd_snap_save(a):
    c = conn(a.db)
    n = 0
    for p in _iter_source(a.src):
        rel = os.path.relpath(p, a.src)
        try:
            m = _md5(p)
        except OSError:
            continue
        c.execute("INSERT OR REPLACE INTO file_snap (path,md5,lines,night_id) VALUES (?,?,?,?)",
                  (rel, m, 0, a.night))
        n += 1
    c.commit()
    print(f"snapshot saved: {n} files (night {a.night})")


def cmd_snap_diff(a):
    c = conn(a.db)
    prev = c.execute("SELECT night_id FROM file_snap WHERE night_id<? ORDER BY night_id DESC LIMIT 1",
                     (a.night,)).fetchone()
    changed = []
    if prev:
        old = {r["path"]: r["md5"] for r in c.execute("SELECT path,md5 FROM file_snap WHERE night_id=?", (prev["night_id"],))}
        for p in _iter_source(a.src):
            rel = os.path.relpath(p, a.src)
            m = _md5(p)
            if rel not in old:
                changed.append(rel)
            elif old[rel] != m:
                changed.append(rel)
    print(json.dumps({"prev_night": prev["night_id"] if prev else None, "changed": changed}))


def cmd_mark_stale(a):
    """按变更文件列表，把 input_range 命中的分片标 stale（精确失效）"""
    c = conn(a.db)
    files = [x.strip() for x in a.files.split(",") if x.strip()]
    hit = []
    for r in c.execute("SELECT id,input_range FROM chunk WHERE status='done'"):
        rng = (r["input_range"] or "*").split(";")
        for pat in rng:
            pat = pat.strip()
            if pat == "*":
                hit.append(r["id"])
                break
            for f in files:
                if fnmatch.fnmatch(f, pat) or fnmatch.fnmatch(os.path.basename(f), os.path.basename(pat)):
                    hit.append(r["id"])
                    break
            else:
                continue
            break
    for cid in hit:
        c.execute("UPDATE chunk SET status='stale' WHERE id=?", (cid,))
        c.execute("UPDATE task SET status='stale' WHERE id=?", (cid.split("#")[0],))
    c.commit()
    print(json.dumps({"stale": hit}))


# ---------------------------------------------------------------- 运行记录 / 统计
def cmd_run_start(a):
    c = conn(a.db)
    c.execute("INSERT OR REPLACE INTO run (night_id,date,start_at) VALUES (?,?,?)",
              (a.night, a.date, _now()))
    c.commit()
    print(a.night)


def cmd_run_end(a):
    c = conn(a.db)
    c.execute("""UPDATE run SET end_at=?, stop_reason=?, tps=?, chars_out=?, chunks_done=?, chunks_failed=?, carry_over=?
                 WHERE night_id=?""",
              (_now(), a.reason, a.tps, a.chars, a.done, a.failed, a.carry, a.night))
    c.commit()


def cmd_last_night(a):
    c = conn(a.db)
    r = c.execute("SELECT COALESCE(MAX(night_id),0) n FROM run").fetchone()
    print(r["n"])


def cmd_stats(a):
    c = conn(a.db)
    t = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM task GROUP BY status")}
    k = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM chunk GROUP BY status")}
    facts = c.execute("SELECT COUNT(*) n FROM fact").fetchone()["n"]
    print(json.dumps({"tasks": t, "chunks": k, "facts": facts}))


def cmd_report(a):
    """输出跨夜续跑摘要所需的 JSON"""
    c = conn(a.db)
    chunks = [dict(r) for r in c.execute("SELECT * FROM chunk ORDER BY task_id, seq")]
    tasks = [dict(r) for r in c.execute("SELECT * FROM task ORDER BY priority, id")]
    runs = [dict(r) for r in c.execute("SELECT * FROM run ORDER BY night_id")]
    print(json.dumps({"tasks": tasks, "chunks": chunks, "runs": runs}, ensure_ascii=False))


def cmd_sql(a):
    """执行任意 SQL 并以 TSV 输出（供 bash 取值）"""
    c = conn(a.db)
    try:
        rows = c.execute(a.q).fetchall()
    except Exception as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
    if a.write:
        c.commit()
    for r in rows:
        print("\t".join("" if v is None else str(v) for v in r))


def cmd_task_status(a):
    c = conn(a.db)
    c.execute("UPDATE task SET status=? WHERE id=?", (a.status, a.id))
    if a.status in ("dropped", "failed"):
        c.execute("UPDATE chunk SET status='failed' WHERE task_id=? AND status<>'done'", (a.id,))
    c.commit()
    print(f"task {a.id} -> {a.status}")


def cmd_metric(a):
    c = conn(a.db)
    c.execute("INSERT INTO metric (night_id,kind,key,value,detail) VALUES (?,?,?,?,?)",
              (a.night, a.kind, a.key, a.value, a.detail))
    c.commit()


def cmd_metrics_dump(a):
    c = conn(a.db)
    rows = [dict(r) for r in c.execute("SELECT * FROM metric WHERE kind=? ORDER BY night_id", (a.kind,))]
    print(json.dumps(rows, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="夜间编排状态库")
    p.add_argument("--db", required=True)
    p.add_argument("--schema", default=DEFAULT_SCHEMA)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.set_defaults(fn=cmd_init)

    s = sub.add_parser("load-queue"); s.add_argument("--queue", required=True); s.add_argument("--taskdir", required=True)
    s.add_argument("--fresh", action="store_true"); s.set_defaults(fn=cmd_load_queue)

    s = sub.add_parser("next-chunk"); s.add_argument("--night", type=int, default=0)
    s.add_argument("--only-task", default=""); s.add_argument("--exclude-file", default="")
    s.add_argument("--no-dep", action="store_true", help="忽略依赖，用于干跑列出全部待办")
    s.set_defaults(fn=cmd_next_chunk)

    s = sub.add_parser("chunk-start"); s.add_argument("--id", required=True); s.add_argument("--night", type=int, default=0)
    s.set_defaults(fn=cmd_chunk_start)

    s = sub.add_parser("chunk-done"); s.add_argument("--id", required=True); s.add_argument("--night", type=int, default=0)
    s.add_argument("--chars", type=int, default=0); s.add_argument("--seconds", type=int, default=0)
    s.add_argument("--handoff", default=""); s.set_defaults(fn=cmd_chunk_done)

    s = sub.add_parser("chunk-fail"); s.add_argument("--id", required=True); s.add_argument("--error", default="")
    s.set_defaults(fn=cmd_chunk_fail)

    s = sub.add_parser("reset-running"); s.set_defaults(fn=cmd_reset_running)

    s = sub.add_parser("ghosts"); s.add_argument("--work", required=True); s.set_defaults(fn=cmd_ghosts)

    s = sub.add_parser("fact-upsert"); s.add_argument("--pk", required=True); s.add_argument("--claim", required=True)
    s.add_argument("--evidence", default=""); s.add_argument("--task", default=""); s.add_argument("--night", type=int, default=0)
    s.add_argument("--confidence", default="normal"); s.set_defaults(fn=cmd_fact_upsert)

    s = sub.add_parser("fact-export"); s.add_argument("--file", required=True); s.add_argument("--max-chars", type=int, default=8000)
    s.set_defaults(fn=cmd_fact_export)

    s = sub.add_parser("snap-save"); s.add_argument("--src", required=True); s.add_argument("--night", type=int, required=True)
    s.set_defaults(fn=cmd_snap_save)

    s = sub.add_parser("snap-diff"); s.add_argument("--src", required=True); s.add_argument("--night", type=int, required=True)
    s.set_defaults(fn=cmd_snap_diff)

    s = sub.add_parser("mark-stale"); s.add_argument("--files", required=True); s.set_defaults(fn=cmd_mark_stale)

    s = sub.add_parser("run-start"); s.add_argument("--night", type=int, required=True); s.add_argument("--date", default="")
    s.set_defaults(fn=cmd_run_start)

    s = sub.add_parser("run-end"); s.add_argument("--night", type=int, required=True); s.add_argument("--reason", default="")
    s.add_argument("--tps", type=float, default=0); s.add_argument("--chars", type=int, default=0)
    s.add_argument("--done", type=int, default=0); s.add_argument("--failed", type=int, default=0)
    s.add_argument("--carry", type=int, default=0); s.set_defaults(fn=cmd_run_end)

    s = sub.add_parser("last-night"); s.set_defaults(fn=cmd_last_night)
    s = sub.add_parser("stats"); s.set_defaults(fn=cmd_stats)
    s = sub.add_parser("report"); s.set_defaults(fn=cmd_report)

    s = sub.add_parser("sql"); s.add_argument("--q", required=True); s.add_argument("--write", action="store_true")
    s.set_defaults(fn=cmd_sql)

    s = sub.add_parser("task-status"); s.add_argument("--id", required=True); s.add_argument("--status", required=True)
    s.set_defaults(fn=cmd_task_status)

    s = sub.add_parser("metric"); s.add_argument("--night", type=int, default=0); s.add_argument("--kind", required=True)
    s.add_argument("--key", required=True); s.add_argument("--value", type=float, required=True)
    s.add_argument("--detail", default=""); s.set_defaults(fn=cmd_metric)

    s = sub.add_parser("metrics-dump"); s.add_argument("--kind", required=True); s.set_defaults(fn=cmd_metrics_dump)

    a = p.parse_args()
    rc = a.fn(a)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
