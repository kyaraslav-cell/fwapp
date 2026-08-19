VENV := .venv/bin

.PHONY: check run dev

check:
	$(VENV)/ruff check app tests
	$(VENV)/mypy --strict app/core app/rules app/features app/auth app/jobs app/discover app/geo
	$(VENV)/pytest -q

run:
	$(VENV)/uvicorn app.web.app:app --host 0.0.0.0 --port 8000

dev:
	$(VENV)/uvicorn app.web.app:app --reload --port 8000
