SHELL=/bin/bash
TAG := $(or $(TAG), 1.3.0)

env:
	set -o allexport && source dev.env && set +o allexport

run:
	flask -A app/app run --host=0.0.0.0

build_docker:
	docker build . -t ghcr.io/aridhia-open-source/federated_node_run:${TAG}

build_docker_dev:
	docker build . -t ghcr.io/aridhia-open-source/federated_node_run:${TAG}-v$(shell git rev-parse --short HEAD)

tests_local:
	./run_tests.sh

tests_ci:
	./run_tests.sh ci

migrate:
	echo "Use 'python -m alembic revision --autogenerate -m'"
