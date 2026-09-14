.PHONY: dev test lint clean

dev:
	uv run uvicorn src.brain.main:app --reload --port 8000

test:
	uv run pytest tests/ -v --tb=short

lint:
	uv run ruff check src/ tests/

clean:
	rm -rf .venv data/*.db data/*.json
