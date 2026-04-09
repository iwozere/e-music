cd c:\dev\cursor\e-music
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

cd c:\dev\cursor\e-music\backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000