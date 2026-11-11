.PHONY: install install-static run dev fmt lint typecheck test audit validate

install: install-static
	uv sync

install-static:
	./update_htmx.sh
	./update_editorjs.sh
	./update_cropper.sh

run:
	uv run fastapi run app/main.py --port 3005

dev:
	uv run fastapi dev app/main.py --port 3005

fmt:
	uv run ruff format .
	uv run ruff check --fix .

# Same checks as CI: nothing is auto-fixed here.
lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run basedpyright

# The UI tests need the static JS (make install-static) and a Playwright browser
# (uv run playwright install chromium).
test:
	uv run pytest

# Known vulnerabilities in the locked dependencies (uv preview feature)
audit:
	uv audit --preview-features audit-command

validate: lint typecheck audit test
