# 🕵️ MysteryDetective

AI Mystery Detective game — Python + FastAPI + vanilla HTML/CSS/JS. Groq (`openai/gpt-oss-120b`) generates a full case upfront; the server keeps ONE consistent truth (culprit/evidence never change mid-game).

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
