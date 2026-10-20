# Platine: dev, container and Kubernetes tasks (run `make` for help).
# Podman by default, `make CONTAINER=docker ...` for Docker.
CONTAINER ?= podman
UV        ?= $(shell command -v uv 2>/dev/null || echo .venv/bin/uv)
DENO      ?= .venv/bin/deno
IMAGE     ?= localhost/platine
TAG       ?= latest
REGISTRY  ?= ghcr.io/baptgosse
RELEASE   ?= platine
NAMESPACE ?= platine
CHART     := charts/platine
HELM_ARGS ?=
PORT      ?= 8320
TRIVY     ?= trivy
COV       := coverage
# First-party browser code: main.js (bootstrap) and sw.js (service worker) are not unit-tested.
JS_COV    := --include='platine/static/js/' --exclude='main\.js'

# yt-dlp looks for `deno` in PATH: the one from the venv has to be there.
export PATH := $(CURDIR)/.venv/bin:$(PATH)

# Podman builds OCI images by default, which drop HEALTHCHECK: force the Docker format.
ifeq ($(CONTAINER),podman)
BUILD_FLAGS ?= --format docker
# Otherwise `podman compose` picks docker-compose when it is installed, which needs the Podman
# socket (systemctl --user enable --now podman.socket). podman-compose works without it.
export PODMAN_COMPOSE_PROVIDER ?= podman-compose
endif

.DEFAULT_GOAL := help
.PHONY: help install dev test test-network test-js lint fmt typecheck check update-ytdlp \
	    coverage coverage-python coverage-js coverage-badges \
	    image run up down logs push scan scan-image helm-lint helm-template helm-install

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- Development -------------------------------------------------------------

install: ## Install dependencies (dev included) into .venv
	$(UV) sync

dev: ## Run the dev server with auto-reload on http://localhost:8320
	$(UV) run uvicorn platine.web:app --reload --port $(PORT)

test: ## Run the Python tests
	$(UV) run pytest

test-network: ## Run the tests that really download from the Internet
	$(UV) run pytest -m network

test-js: ## Run the frontend JavaScript tests (deno)
	$(DENO) test tests/js

lint: ## Check style and code quality (ruff, pylint)
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run pylint platine tests scripts

fmt: ## Fix style automatically (ruff)
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## Check types (mypy)
	$(UV) run mypy

check: lint typecheck coverage-python coverage-js helm-lint ## Everything CI checks, 100 % coverage gates included

update-ytdlp: ## Upgrade yt-dlp to its latest release (when a site breaks)
	$(UV) lock --upgrade-package yt-dlp
	$(UV) sync

# --- Coverage ----------------------------------------------------------------

coverage-python: ## Python coverage: XML, HTML and lcov reports, fails below 100 %
	rm -rf $(COV)/python
	$(UV) run pytest --cov --cov-report=term --cov-report=xml:$(COV)/python/coverage.xml \
	    --cov-report=html:$(COV)/python/html --cov-report=lcov:$(COV)/python/lcov.info
	$(UV) run python scripts/coverage_gate.py --name Python $(COV)/python/lcov.info

coverage-js: ## JS coverage: lcov and HTML reports, fails below 100 %
	rm -rf $(COV)/js
	$(DENO) test --coverage=$(COV)/js/raw tests/js
	$(DENO) coverage $(COV)/js/raw $(JS_COV) --lcov --output=$(COV)/js/lcov.info
	@# deno test already wrote an unfiltered HTML report there: start from a clean directory.
	rm -rf $(COV)/js/raw/html
	$(DENO) coverage $(COV)/js/raw $(JS_COV) --html
	mv $(COV)/js/raw/html $(COV)/js/html
	$(UV) run python scripts/coverage_gate.py --name JS $(COV)/js/lcov.info

coverage-badges: ## SVG coverage badges in coverage/badges/
	mkdir -p $(COV)/badges
	@if [ -f $(COV)/python/coverage.xml ]; then \
	    $(UV) run genbadge coverage -l -n "python coverage" -i $(COV)/python/coverage.xml -o $(COV)/badges/python.svg; fi
	@if [ -f $(COV)/js/lcov.info ]; then \
	    $(UV) run lcov_cobertura $(COV)/js/lcov.info -b . -o $(COV)/js/cobertura.xml && \
	    $(UV) run genbadge coverage -l -n "js coverage" -i $(COV)/js/cobertura.xml -o $(COV)/badges/js.svg; fi

coverage: ## Python + JS coverage with HTML reports and badges (target: 100 %)
	@status=0; $(MAKE) --no-print-directory -k coverage-python coverage-js || status=$$?; \
	$(MAKE) --no-print-directory coverage-badges; \
	echo; echo "HTML reports:"; \
	echo "  $(COV)/python/html/index.html"; \
	echo "  $(COV)/js/html/index.html"; \
	exit $$status

# --- Container ---------------------------------------------------------------

image: ## Build the image (IMAGE and TAG variables)
	$(CONTAINER) build $(BUILD_FLAGS) -t $(IMAGE):$(TAG) .

run: image ## Run the image locally with a read-only filesystem
	$(CONTAINER) run --rm -it --read-only --tmpfs /tmp:rw,size=2g,mode=1777 \
	    --cap-drop ALL --security-opt no-new-privileges \
	    -p 127.0.0.1:$(PORT):8320 $(IMAGE):$(TAG)

up: ## Start with compose (podman compose / docker compose)
	$(CONTAINER) compose up -d --build

down: ## Stop compose
	$(CONTAINER) compose down

logs: ## Follow compose logs
	$(CONTAINER) compose logs -f

push: image ## Push the image to REGISTRY/platine:TAG (default ghcr.io/baptgosse)
	$(CONTAINER) tag $(IMAGE):$(TAG) $(REGISTRY)/platine:$(TAG)
	$(CONTAINER) push $(REGISTRY)/platine:$(TAG)

# --- Security ----------------------------------------------------------------

scan: ## Scan dependencies, secrets, Dockerfile and chart for known issues (Trivy)
	$(TRIVY) fs --config trivy.yaml .

# The image goes through a tar file on disk: no container socket needed, and /tmp is often in RAM.
scan-image: image ## Scan the image for known vulnerabilities and secrets (Trivy)
	@rm -rf .scan && mkdir .scan && trap 'rm -rf .scan' EXIT && \
	    $(CONTAINER) save -q -o .scan/image.tar $(IMAGE):$(TAG) && \
	    $(TRIVY) image --config trivy.yaml --scanners vuln,secret --input .scan/image.tar

# --- Kubernetes --------------------------------------------------------------

helm-lint: ## Lint the Helm chart
	helm lint $(CHART)

helm-template: ## Print the generated Kubernetes manifests
	helm template $(RELEASE) $(CHART) --namespace $(NAMESPACE) $(HELM_ARGS)

helm-install: ## Install or upgrade on the current cluster
	helm upgrade --install $(RELEASE) $(CHART) --namespace $(NAMESPACE) --create-namespace \
	    --set image.repository=$(REGISTRY)/platine --set image.tag=$(TAG) $(HELM_ARGS)
