-- 跨夜编排状态库（SQLite）。由 lib/db.py 初始化。
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS task (
  id           TEXT PRIMARY KEY,
  phase        TEXT,
  title        TEXT,
  prompt       TEXT,
  depends      TEXT,
  output       TEXT,
  chunks_file  TEXT,
  priority     INTEGER DEFAULT 5,
  timeout_min  INTEGER DEFAULT 25,
  retries      INTEGER DEFAULT 2,
  check_rule   TEXT,
  max_out      INTEGER DEFAULT 0,        -- 按任务覆盖输出 token 预算（0=用 MAX_OUTPUT_TOKENS）
  status       TEXT DEFAULT 'pending',  -- pending/running/done/partial/failed/blocked/stale/dropped
  attempt      INTEGER DEFAULT 0,
  night_id     INTEGER,
  started_at   INTEGER,
  finished_at  INTEGER,
  last_error   TEXT
);

-- 分片级断点：跨夜续跑的真正粒度
CREATE TABLE IF NOT EXISTS chunk (
  id          TEXT PRIMARY KEY,          -- task_id#seq
  task_id     TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  input_range TEXT,                      -- 分号分隔的 glob，用于白天变更失效判定
  output_part TEXT,                      -- 相对 WORK 的路径
  status      TEXT DEFAULT 'pending',    -- pending/running/done/failed/stale
  attempt     INTEGER DEFAULT 0,
  night_id    INTEGER,
  chars_out   INTEGER DEFAULT 0,
  seconds     INTEGER DEFAULT 0,
  handoff     TEXT,
  last_error  TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunk_status ON chunk(status);
CREATE INDEX IF NOT EXISTS idx_chunk_task   ON chunk(task_id);

-- 每晚一次运行记录
CREATE TABLE IF NOT EXISTS run (
  night_id     INTEGER PRIMARY KEY,
  date         TEXT,
  start_at     INTEGER,
  end_at       INTEGER,
  stop_reason  TEXT,                     -- schedule/soft/hard/manual/crash
  tps          REAL,
  chars_out    INTEGER,
  chunks_done  INTEGER,
  chunks_failed INTEGER,
  carry_over   INTEGER
);

-- 源码快照：用于白天变更检测
CREATE TABLE IF NOT EXISTS file_snap (
  path     TEXT,
  md5      TEXT,
  lines    INTEGER,
  night_id INTEGER,
  PRIMARY KEY (path, night_id)
);

-- 结构化事实库（跨夜保持，幂等 upsert）
CREATE TABLE IF NOT EXISTS fact (
  pk        TEXT PRIMARY KEY,            -- 文件:行号:结论类型
  claim     TEXT,
  evidence  TEXT,
  task_id   TEXT,
  night_id  INTEGER,
  confidence TEXT DEFAULT 'normal',      -- normal/low
  created_at INTEGER
);

-- 指标采样（供 metrics.py 汇总）
CREATE TABLE IF NOT EXISTS metric (
  night_id INTEGER,
  kind     TEXT,                         -- preflight/chunk/experiment
  key      TEXT,
  value    REAL,
  detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_metric_kind ON metric(kind, key);
