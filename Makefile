.PHONY: install dev-install dev-tools run dev test lint clean uninstall help

help:
	@echo "VeloFetch - Mevcut Komutlar:"
	@echo ""
	@echo "  make install     - Bağımlılıkları ve uygulamayı kurar"
	@echo "  make dev-install - Geliştirme bağımlılıklarıyla kurar ([dev])"
	@echo "  make run         - Uygulamayı çalıştırır"
	@echo "  make dev         - Geliştirici modunda (venv) çalıştırır"
	@echo "  make test        - Testleri çalıştırır (pytest yoksa [dev] kurulur)"
	@echo "  make lint        - ruff + sözdizimi kontrolü yapar (ruff yoksa [dev] kurulur)"
	@echo "  make clean       - Geçici dosyaları temizler"
	@echo "  make uninstall   - Uygulamayı kaldırır"
	@echo ""

install:
	pip install -r requirements.txt
	pip install -e .

dev-install:
	pip install -e ".[dev]"

# pytest and ruff live only in the [dev] extra, so `make install` does not
# bring them in. Pull them in on demand, and only when they are missing, so
# the documented install -> test/lint path works without a reinstall on
# every run.
dev-tools:
	@command -v pytest >/dev/null 2>&1 && command -v ruff >/dev/null 2>&1 \
		|| $(MAKE) dev-install

run:
	python -m vf

dev:
	@if [ ! -d "venv" ]; then \
		echo "Sanal ortam oluşturuluyor..."; \
		python3 -m venv venv; \
		venv/bin/pip install -r requirements.txt; \
	fi
	venv/bin/python -m vf

test: dev-tools
	QT_QPA_PLATFORM=offscreen pytest tests/ -v

lint: dev-tools
	ruff check .
	python -m compileall -q vf tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/

uninstall:
	pip uninstall -y velofetch
