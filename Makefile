.PHONY: up down build logs migrate kafka-topics test health clean

up:
	docker-compose up -d

down:
	docker-compose down

down-volumes:
	docker-compose down -v

build:
	docker-compose build

build-fresh:
	docker-compose build --no-cache

logs:
	docker-compose logs -f

logs-%:
	docker-compose logs -f $*

migrate-identity:
	docker-compose exec identity-service alembic upgrade head

migrate-app:
	docker-compose exec kpi-service alembic upgrade head
	docker-compose exec governance-service alembic upgrade head
	docker-compose exec ingestion-service alembic upgrade head
	docker-compose exec monitoring-service alembic upgrade head
	docker-compose exec notification-service alembic upgrade head

migrate: migrate-identity migrate-app

kafka-topics:
	bash infrastructure/kafka/create_topics.sh localhost:29092

test:
	docker-compose run --rm identity-service pytest tests/ -v
	docker-compose run --rm ingestion-service pytest tests/ -v
	docker-compose run --rm processing-service pytest tests/ -v
	docker-compose run --rm kpi-service pytest tests/ -v
	docker-compose run --rm governance-service pytest tests/ -v
	docker-compose run --rm monitoring-service pytest tests/ -v
	docker-compose run --rm notification-service pytest tests/ -v

health:
	@echo "=== CDS Service Health ==="
	@curl -sf http://localhost:8001/health/live && echo " identity-service: OK" || echo " identity-service: FAILED"
	@curl -sf http://localhost:8002/health/live && echo " ingestion-service: OK" || echo " ingestion-service: FAILED"
	@curl -sf http://localhost:8003/health/live && echo " processing-service: OK" || echo " processing-service: FAILED"
	@curl -sf http://localhost:8004/health/live && echo " governance-service: OK" || echo " governance-service: FAILED"
	@curl -sf http://localhost:8005/health/live && echo " kpi-service: OK" || echo " kpi-service: FAILED"
	@curl -sf http://localhost:8006/health/live && echo " monitoring-service: OK" || echo " monitoring-service: FAILED"
	@curl -sf http://localhost:8007/health/live && echo " notification-service: OK" || echo " notification-service: FAILED"

shell-%:
	docker-compose exec $* /bin/bash

install-shared:
	cd shared && pip install -e .

minio-init:
	docker-compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin_secret
	docker-compose exec minio mc mb --ignore-existing local/cds-raw
	docker-compose exec minio mc mb --ignore-existing local/cds-validated
	docker-compose exec minio mc mb --ignore-existing local/cds-processed
	docker-compose exec minio mc mb --ignore-existing local/cds-reports
	docker-compose exec minio mc mb --ignore-existing local/cds-archived

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
