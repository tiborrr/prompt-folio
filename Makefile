.PHONY: install install-static run dev

install:
	uv sync
	./update_htmx.sh
	./update_editorjs.sh

install-static:
	./update_htmx.sh
	./update_editorjs.sh

run:
	uv run fastapi run app/main.py --port 3005

dev:
	uv run fastapi dev app/main.py --port 3005
