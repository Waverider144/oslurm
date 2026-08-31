.PHONY: build test demo clean

build:
	cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
	cmake --build build

test: build
	ctest --test-dir build --output-on-failure
	python3 tests/test_python_provider.py

demo: build
	python3 adapters/gmat/gmat_comm_ephemeris.py --input ../docs/visualization/gmat-events.json --output build/demo/contacts.json
	./build/gmat_comm_demo

clean:
	rm -rf build
