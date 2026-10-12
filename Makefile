.PHONY: up down logs test ingest pull-model
up:        ## build and start Postgres + app (http://localhost:8000)
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f app
test:      ## run the automated suite (SQLite, fake LLM; no Docker/Ollama needed)
	cd backend && pip install -q -r requirements-dev.txt && python -m pytest -q
ingest:    ## force a full re-ingest inside the running container
	docker compose exec app python -m app.kb.ingest --fetch
pull-model:
	ollama pull $${OLLAMA_MODEL:-qwen2.5:7b}
