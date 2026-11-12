# Runs a tool from a PyPI package in a throwaway env: uvx if installed, else pipx.
RUN = $(if $(shell command -v uvx),uvx --from,pipx run --spec)

.PHONY: release
release:
	@test -z "$$(git status --porcelain)" || { echo "release: commit or stash your changes first"; exit 1; }
	python3 -m unittest test_server
	rm -rf build dist
	$(RUN) build pyproject-build
	$(RUN) twine twine check dist/*
	$(RUN) twine twine upload dist/*
