.PHONY: install format lint type test coverage build check release-check clean

install:
	uv sync --group dev

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

type:
	uv run mypy src/flru

test:
	uv run pytest

coverage:
	uv run pytest --cov=flru --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=html

build:
	uv build

check: lint type coverage build
	uvx twine check dist/*

release-check:
	uv run python scripts/check_release.py

clean:
	rm -rf .coverage .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml coverage.json build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
