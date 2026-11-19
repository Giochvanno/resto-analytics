.PHONY: venv install lock lint format typecheck test check run docker-build docker-run

PYTHON ?= python3

# Виртуальное окружение + зависимости точно по lock-файлу
venv:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt
	.venv/bin/pip install -e . --no-deps
	@echo "Готово. Активируйте: source .venv/bin/activate"

# В уже активированном окружении
install:
	pip install -r requirements-dev.txt
	pip install -e . --no-deps

# Пересобрать lock-файлы после изменения зависимостей в pyproject.toml
lock:
	uv pip compile pyproject.toml --universal --python-version 3.11 -o requirements.txt
	uv pip compile pyproject.toml --extra dev --universal --python-version 3.11 -o requirements-dev.txt

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
	docker run --rm -p 8000:8000 --env-file .env resto-analytics
