# llm-legacy-code-pipeline

基于 LLM 的老旧代码库分析流水线：跨夜可续跑的编排器 + 验证工装。

## 组成

- `tools/nightly/` —— 跨夜编排器（分片、断点续跑、三级停止、看门狗、L0 图层、原子写）
- `tools/validate/` —— 验证工装（合成语料生成、评分、指标、混沌测试）

## 快速开始

详见 [`tools/nightly/README.md`](tools/nightly/README.md)。

```bash
cd tools/nightly
./nightly.sh --dry-run     # 排障首选，不调模型，先看续跑清单
./nightly.sh               # 正式跑一夜（默认 --resume）
./summarize.sh --final     # 生成跨夜最终报告
```

## 设计要点

- **事实由脚本给**：每晚 `lib/l0.py` 扫描源码生成 `L0-inventory.md`（行数/方法数/依赖边），模型只写叙述，避免编造统计。
- **调用通道**：默认 `direct`（直连 Ollama `/api/generate`，`think=false`），事实层由脚本预取注入。
- **跨夜续跑**：分片级断点、原子写、看门狗、幂等合并，支持 SIGTERM 优雅停止与崩溃恢复。
