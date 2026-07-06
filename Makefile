.PHONY: up down migrate fixtures test

up:
	docker compose up -d

down:
	docker compose down

migrate:
	python infra/init_qdrant.py
	for f in infra/migrations/*.sql; do \
		docker compose exec -T postgres psql -U $${POSTGRES_USER:-pocketlaw} -d $${POSTGRES_DB:-pocketlaw} -f - < $$f; \
	done

fixtures:
	python -m agent.fixtures.load_fixtures

test:
	pytest
