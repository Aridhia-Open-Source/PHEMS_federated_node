SHELL=/bin/bash
TAG := $(or $(TAG), 1.3.0)

.PHONY: env run build_docker build_docker_dev tests_integration tests_local \
	tests_ci run_tests migrate pip_compile pip_compile_dev

env:
	set -o allexport && source dev.env && set +o allexport

run:
	flask -A app/app run --host=0.0.0.0

build_docker:
	docker build . -t ghcr.io/aridhia-open-source/federated_node_run:${TAG}

build_docker_dev:
	docker build . -t ghcr.io/aridhia-open-source/federated_node_run:${TAG}-v$(shell git rev-parse --short HEAD)

tests_integration:
	./run_integration_tests.sh

tests_local:
	./run_tests.sh

tests_ci:
	./run_tests.sh ci

# Backwards-compatible alias for tests_local. Without this explicit (and .PHONY)
# rule, `make run_tests` would fall through to make's implicit rules and try to
# build an executable named run_tests out of run_tests.sh.
run_tests: tests_local

migrate:
	echo "Use 'python -m alembic revision --autogenerate -m'"

pip_compile:
	../scripts/pip_compile.sh .

pip_compile_dev:
	../scripts/pip_compile.sh . --extra=dev --output-file=requirements-dev.txt
