.PHONY: test test-ui lint run compose fmt sweep-demo

export PYTHONPATH := src

test:
	uv run pytest -q

test-ui:
	uv run pytest -q -m ui

lint:
	uv run ruff check src tests

fmt:
	uv run ruff check --fix src tests

run:
	mkdir -p data
	uv run uvicorn rootfold.main:app --host 0.0.0.0 --port 8000

compose:
	docker compose up --build

import-example:
	@echo "Start the API first (make run), then:"
	@echo "  TOKEN=$$(curl -s -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"admin\",\"password\":\"changeme\"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"access_token\"])')"
	@echo "  curl -X POST http://127.0.0.1:8000/api/topology/import-example -H \"Authorization: Bearer $$TOKEN\""

import-netbox-fixture:
	uv run rootfold import-netbox --fixture tests/fixtures/netbox.json
