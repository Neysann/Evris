# E.V.R.I.S. — Local Personal AI & Polymath Assistant

**E.V.R.I.S.** is a 100% local, privacy-first personal AI assistant and autonomous PC agent inspired by **J.A.R.V.I.S.**, using a **3-Tier Multi-Model Complexity & Domain Router** powered by Ollama and a **Rich live-streaming terminal interface**:
- **FAST Model (`qwen3.5:4b`)** *(Cyan)*: Instant responses for everyday questions, status checks, and quick PC commands.
- **PRO Model (`qwen3.5:9b`)** *(Yellow/Amber)*: Deep polymath reasoning across **Science, Finance, Computer Science, and Strategy**, sized for a **32 GB RAM + RTX 5060 (8 GB VRAM)** workstation.
- **LIMITLESS Mode (`huihui_ai/qwen3.5-abliterated:9b`)** *(Magenta)*: Uncensored, refusal-removed Qwen 3.5 model (`/mode limitless`, or auto-escalated in `/mode auto` if `FAST`/`PRO` refuses) for unrestricted answers without safety refusals or moralizing.

---

## Terminal Interface Preview

![E.V.R.I.S. Terminal Interface](./docs/evris-terminal.svg)

---

## Key Features & Options Available

### 1. Dynamic Terminal UI & 3-Way Auto Routing (`evris.py`, `backend/app/core/router.py`)
- **Live Streaming & Color-Coded Mode Panels**: Responses stream token-by-token inside Rich Markdown panels color-coded by active tier (**Cyan** = `FAST`, **Amber** = `PRO`, **Magenta** = `LIMITLESS`, **Red** = `REFUSED`) with a 12 FPS spinner, elapsed timer, and live `tok/s` speed.
- **`FAST [GENERAL]`**: Short conversational prompts and quick actions route to `qwen3.5:4b`.
- **`PRO [FINANCE | SCIENCE | TECH | STRATEGY]`**: Specialist domain questions, code generation, and complex analytical prompts route to `qwen3.5:9b` with domain-specific first-principles framing.
- **`LIMITLESS`**: Triggered manually (`/mode limitless`), proactively on uncensored/sensitive keywords, or automatically in `/mode auto` when `FAST`/`PRO` returns a safety refusal.
- **Smart Security Confirmation & RAM Guardrail**: Launches any installed app/shortcut without a restrictive whitelist while prompting `[y/N]` for risky scripts/shells or sensitive files (`.env`, `.ssh`, etc.), and checks `pro_min_free_ram_gb` (`5.5 GB`) before loading 9B models.
- **Persistent Settings & Logging**: Mode, Pro availability, RAM threshold, and confirmation toggle persist across restarts in SQLite; diagnostics log to `backend/data/evris.log`.

### 2. Interactive Terminal Commands (`evris.py`)

| Command | Description |
| :--- | :--- |
| `/mode auto` | Automatic 3-way routing between **FAST**, **PRO**, and **LIMITLESS** *(with auto-escalation on refusal, default)* |
| `/mode fast` | Force all prompts to use the **FAST** model (`qwen3.5:4b`) |
| `/mode pro` | Force all prompts to use the **PRO** model (`qwen3.5:9b`) |
| `/mode limitless` | Force all prompts to use the uncensored **LIMITLESS** model (`huihui_ai/qwen3.5-abliterated:9b`) |
| `/pro on` \| `/pro off` | Toggle the **PRO** model node online/offline to test strict refusal behavior |
| `/confirm on` \| `/confirm off` | Toggle smart `[y/N]` security confirmations for risky scripts or sensitive files |
| `/ram [gb]` | Check or set the heavy-model RAM safety threshold (e.g. `/ram 5.5`) |
| `/memories` | List all permanent facts stored in long-term SQLite memory |
| `/forget <id\|all>` | Delete a specific long-term memory by ID or clear all stored facts |
| `/tools` | Display all autonomous tools registered with the agent |
| `/status` | Display live CPU/RAM usage, active models, and memory count |
| `/clear` | Clear conversation history while preserving long-term memories |
| `/exit` | Exit Evris |

### 3. Autonomous Agent Tools (`backend/app/tools/`)

| Tool Name | Capability | Example Trigger |
| :--- | :--- | :--- |
| `save_memory` | Stores permanent user facts & preferences in SQLite across sessions | *"Remember that my target return is 12%"* |
| `get_market_quote` | Fetches live stock, index, or crypto prices & 24h change (`NVDA`, `BTC-USD`, `SPY`) | *"What is the current price of NVDA and BTC-USD?"* |
| `calculate_math` | Safe AST-based scientific & financial calculator (`sqrt`, `log`, exponents, compounding) | *"Calculate $15,000 compounded at 8.5% for 10 years"* |
| `open_application` | Launches any installed desktop application (by name, shortcut, or path) or URL | *"Open Discord"* / *"Open the calculator"* |
| `get_system_report` | Inspects live CPU load, free RAM, disk space, battery, and top RAM-consuming processes | *"Give me a full system report and top processes"* |
| `read_local_file` | Reads and summarizes local code or text files on your computer | *"Read README.md and summarize it"* |
| `list_directory` | Lists files and folders inside any local directory | *"List the files in backend/app"* |
| `web_search` | Searches the live web via DuckDuckGo for current facts or documentation | *"Search the latest Python 3.13 release notes"* |

---

## Quick Start

### 1. Install Ollama & Pull Models
Install [Ollama](https://ollama.com) and download the Qwen 3.5 models (plus the abliterated model for `/mode limitless`):
```bash
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
ollama pull huihui_ai/qwen3.5-abliterated:9b
```

### 2. Install Python Dependencies
```powershell
python -m venv backend/venv
.\backend\venv\Scripts\pip install -r backend/requirements.txt
```

### 3. Launch Evris
From any terminal (or via **`Win + R` $\rightarrow$ `evris`**):
```powershell
evris
```
Or directly with Python:
```powershell
python evris.py
```

---

## Architecture & Roadmap

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for the complete system architecture and multi-phase development roadmap.
