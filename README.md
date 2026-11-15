# E.V.R.I.S. — Local Personal AI & Polymath Assistant

**E.V.R.I.S.** is a 100% local, privacy-first personal AI assistant inspired by **J.A.R.V.I.S.**, using a **Dual-Model Complexity Router** powered by Ollama:
- **FAST Model (`qwen2.5:3b`)**: Instant responses for everyday questions and quick commands.
- **PRO Model (`qwen2.5:7b`)**: Deep polymath reasoning across **Science, Finance, Computer Science, and Strategy**.

## Quick Start

1. Install [Ollama](https://ollama.com) and pull both models:
   ```bash
   ollama pull qwen2.5:3b
   ollama pull qwen2.5:7b
   ```
2. Install Python dependencies:
   ```powershell
   python -m venv backend/venv
   .\backend\venv\Scripts\pip install -r backend/requirements.txt
   ```
3. Run Evris in the terminal:
   ```powershell
   python evris.py
   ```
   *(Or press `Win + R` and type `evris` once registered on Windows.)*

## Architecture & Roadmap

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for the full system architecture and multi-phase roadmap.
