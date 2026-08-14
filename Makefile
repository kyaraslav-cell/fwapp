.PHONY: check run dev

check:
	ruff check app tests
	mypy --strict app/core app/rules app/features
	pytest -q

run:
	uvicorn app.web.app:app --host 0.0.0.0 --port 8000

dev:
	uvicorn app.web.app:app --reload --port 8000
