VENV := .venv/bin

.PHONY: check run dev preflight

check:
	$(VENV)/ruff check app tests
	$(VENV)/mypy --strict app/core app/rules app/features app/auth app/jobs app/discover app/geo app/intel app/media
	$(VENV)/pytest -q

run:
	$(VENV)/uvicorn app.web.app:app --host 0.0.0.0 --port 8000

dev:
	$(VENV)/uvicorn app.web.app:app --reload --port 8000

# Does this machine's setup actually work? Run it where the network is - the
# build sandbox reaches none of these services, so every client in this app is
# unverified until this passes somewhere real. `make preflight ARGS=gemini`
# runs one section.
preflight:
	$(VENV)/python tools/preflight.py $(ARGS)
