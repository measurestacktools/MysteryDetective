# 🕵️ MysteryDetective

AI Mystery Detective game — Python + FastAPI + vanilla HTML/CSS/JS. Groq (`openai/gpt-oss-120b`) generates a full case upfront; the server keeps ONE consistent truth (culprit/evidence never change mid-game).

## Features
- AI-generated cases (suspects, locations, evidence, timeline) at 3 difficulties
- Interrogate suspects, inspect evidence, search locations, hints, private notes
- Accusation + full reveal with clue explanation, replay with a new case

## Requirements
- Python 3.10+
- A free Groq API key ([console.groq.com/keys](https://console.groq.com/keys))
- Internet (AI calls go to Groq)

## Installation
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # add GROQ_API_KEY  (or paste the key in Settings later)
```

## How to play
1. Open a new case, read the intro
2. Question suspects, inspect evidence, search locations, take notes
3. Accuse when confident → reveal explains every clue

## Limitations
- One case at a time (replay overwrites); single in-memory session
- Needs a Groq key + internet; interrogation quality varies by case

- Port **8014**. Backend: `app.py`. Frontend: `static/`.
- Key system: Settings modal → backend live-verify (`models.list`), process-global server memory only (+`DELETE /api/key`); `.env` fallback; `/api/status` presence only; frontend NEVER stores/sends keys.
- Flow: difficulty → `POST /api/new-case` → interrogate / inspect / search / ask → accuse → reveal → replay.

## Run
```powershell
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:8014
```

## Test
```powershell
pip install -r requirements-test.txt
pytest -q
```
