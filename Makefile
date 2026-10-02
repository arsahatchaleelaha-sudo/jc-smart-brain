.PHONY: dev test lint clean

dev:
	PYTHONPATH=src uv run uvicorn brain.main:app --reload --port 8000

test:
	PYTHONPATH=src uv run pytest tests/ -v --tb=short

lint:
	uv run ruff check src/ tests/

clean:
	rm -rf .venv data/*.db data/*.json
