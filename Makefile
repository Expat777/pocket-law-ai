.PHONY: up down migrate test

up:
	docker compose up -d

down:
	docker compose down

migrate:
	python infra/init_qdrant.py
	for f in infra/migrations/*.sql; do \
		docker compose exec -T postgres psql -U $${POSTGRES_USER:-pocketlaw} -d $${POSTGRES_DB:-pocketlaw} -f - < $$f; \
	done

test:
	pytest
