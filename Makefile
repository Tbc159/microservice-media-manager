GENERATED_DIR     := generated
GENERATOR_VERSION := 7.5.0
GENERATOR_JAR     := .cache/openapi-generator-cli-$(GENERATOR_VERSION).jar
GENERATOR_URL     := https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/$(GENERATOR_VERSION)/openapi-generator-cli-$(GENERATOR_VERSION).jar

# Auto-discovery dei domini: ogni openapi/<dominio>/api.yaml e' un dominio.
# Aggiungere openapi/social/api.yaml crea il dominio 'social' senza toccare nulla qui.
DOMAINS := $(notdir $(patsubst %/,%,$(dir $(wildcard openapi/*/api.yaml))))

.PHONY: help install domains validate generate-all clean test lint mock proxy-config seed-source collections collections-check

help: ## elenca i target
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo "  domini rilevati: $(DOMAINS)"

$(GENERATOR_JAR):
	@mkdir -p .cache
	curl -sSL -o $(GENERATOR_JAR) $(GENERATOR_URL)

install: ## installa le dipendenze
	pip install -r requirements.txt -r requirements-dev.txt

domains: ## stampa i domini rilevati
	@echo "$(DOMAINS)"

validate: $(GENERATOR_JAR) ## valida la spec OAS di ogni dominio
	@for d in $(DOMAINS); do \
		echo ">>> validate $$d"; \
		java -jar $(GENERATOR_JAR) validate -i openapi/$$d/api.yaml || exit 1; \
	done

# Genera un singolo dominio (server scaffold + SDK client): make generate-media
generate-%: $(GENERATOR_JAR)
	@echo ">>> genera dominio: $*"
	java -jar $(GENERATOR_JAR) generate -i openapi/$*/api.yaml -g python-flask \
		-o $(GENERATED_DIR)/$*/server -c openapi/config/server-config.yaml \
		--additional-properties=packageName=$*_server
	java -jar $(GENERATOR_JAR) generate -i openapi/$*/api.yaml -g python \
		-o $(GENERATED_DIR)/$*/client -c openapi/config/client-config.yaml \
		--additional-properties=packageName=$*_client,projectName=$*-client

generate-all: validate ## valida + genera server+client per TUTTI i domini
	@for d in $(DOMAINS); do $(MAKE) --no-print-directory generate-$$d; done

mock: ## avvia il mock (tutti i domini, risposte = examples OAS)
	MOCK=1 python -m src.app

proxy-config: ## (ri)genera deploy/proxy/nginx.conf dai domini scoperti
	bash deploy/proxy/gen-nginx-conf.sh

collections: ## (ri)genera i bundle OpenAPI condivisibili in api-collections/
	python3 tools/build_collections.py

collections-check: ## verifica che i bundle in api-collections/ siano allineati alle spec (CI)
	python3 tools/build_collections.py --check

seed-source: ## inserisce dati demo nel dominio source (idempotente, dentro il container)
	docker compose -f docker-compose.source.yml exec source python -m src.domains.source.seed

clean: ## rimuove il codice generato (sicuro: separazione fisica)
	rm -rf $(GENERATED_DIR)

lint: ## linting del SOLO codice custom
	ruff check src/ tests/

test: ## test sul codice custom
	pytest tests/ -v
