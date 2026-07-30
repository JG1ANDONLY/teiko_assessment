# Makefile for the cell-count analysis pipeline.
#
# Graded targets: setup, pipeline, dashboard.

PYTHON ?= python3
PORT   ?= 8501
URL    := http://localhost:$(PORT)

.PHONY: setup pipeline dashboard clean

## Install all dependencies.
setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

## Run the whole pipeline start to finish: build the database, then every analysis.
## Each step reads cell_count.db, so load_data.py must come first.
pipeline:
	$(PYTHON) load_data.py
	$(PYTHON) data_overview.py
	$(PYTHON) statistical_analysis.py
	$(PYTHON) data_subset_analysis.py

## Serve the dashboard and open it in a browser.
##
## Binding 0.0.0.0 is what lets Codespaces forward the port, but it also makes
## Streamlit advertise and auto-open http://0.0.0.0:$(PORT) -- an address
## browsers block, which renders as a blank page. So suppress that with
## --server.headless and open $(URL) ourselves, waiting for the health check
## first so the browser never lands on a refused connection.
dashboard:
	@( for _ in $$(seq 1 60); do \
	       curl -sf $(URL)/_stcore/health >/dev/null 2>&1 && break; \
	       sleep 0.5; \
	   done; \
	   echo ""; echo "  Dashboard ready at $(URL)"; echo ""; \
	   opener="$$BROWSER"; \
	   [ -n "$$opener" ] || opener=$$(command -v xdg-open || command -v open || echo true); \
	   "$$opener" $(URL) >/dev/null 2>&1 || true ) &
	@echo "Starting dashboard, will open $(URL) in your browser..."
	@$(PYTHON) -m streamlit run dashboard.py \
		--server.port=$(PORT) --server.address=0.0.0.0 --server.headless=true

## Remove every generated artifact, leaving only source and the input CSV.
clean:
	rm -f cell_count.db \
	      cell_frequencies.csv \
	      response_boxplots.png response_significance.csv \
	      melanoma_miraclib_pbmc_baseline.csv \
	      baseline_breakdown.csv baseline_b_cell_males.csv
