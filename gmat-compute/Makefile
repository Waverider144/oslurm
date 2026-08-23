.PHONY: configure build test demo clean validate

BUILD_DIR ?= build

configure:
	CCACHE_DISABLE=1 cmake -S . -B $(BUILD_DIR)

build: configure
	CCACHE_DISABLE=1 cmake --build $(BUILD_DIR) -j

test: build
	ctest --test-dir $(BUILD_DIR) --output-on-failure
	python3 -m unittest discover -s tests -p 'test_*.py'

validate:
	python3 tools/calibrate/validate_manifest.py measured/example_gpu/manifest.yaml

demo: build validate
	./scripts/demo.sh

clean:
	rm -rf $(BUILD_DIR)
