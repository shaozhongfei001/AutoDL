# AutoDL — Autonomous Deep Learning Experiment Agent

AutoDL is an autonomous agent that runs end-to-end deep learning experiments:
it *thinks* about a research goal, *executes* experiments on local / SSH /
Slurm backends, *monitors* training with zero LLM cost, and *reflects* on
results to decide the next hypothesis. It is designed to run 24x7 with
bounded, auditable compute.

> This is a from-scratch design. It shares no provenance with the original
> `autoresearcher` project and is not affiliated with any external source
> repository.

## Highlights

- **Autonomous loop** — `THINK → EXECUTE → MONITOR → REFLECT` with a compact
  persistent memory (project brief + rolling log).
- **Multi-backend execution** — local processes, SSH hosts, and Slurm
  clusters behind one interface.
- **Zero-cost monitoring** — poll PID / GPU / log without LLM inference.
- **Config-driven** — LLM provider, backends, and budgets live in
  `config.yaml`.
- **Experiment validity contract** — optional budget enforcement, split-aware
  metric parsing, and comparability fingerprinting for fair, auditable runs.

## Quick start

```bash
# 1. install
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. configure a provider in config.yaml (OPENAI_API_KEY / endpoint)

# 3. create a project brief, then run the loop
export PYTHONPATH=$PWD
nohup .venv/bin/python -m core.loop --project examples/mnist_gpu > run.log 2>&1 &
```

See `examples/` for ready-to-run project briefs (`light_demo`, `mnist_gpu`).

## Layout

```
core/          agent loop, execution backends, monitor, tools, memory
agents/        role definitions (leader, idea, code, writing)
skills/        agent skills / prompts
tests/         unit + integration tests
examples/      runnable project briefs and configs
```

## Development

```bash
.venv/bin/python -m pytest tests/ -q
```

## License

See `LICENSE`.
