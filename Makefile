.PHONY: install lint format typecheck test check run docker-build docker-run

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy

test:
	pytest

# Всё, что гоняет CI
check: lint typecheck test

run:
	uvicorn resto_analytics.web.app:create_app --factory --reload

docker-build:
	docker build -t resto-analytics .

docker-run:
	docker run --rm -p 8000:8000 resto-analytics
