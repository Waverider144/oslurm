.PHONY: test demo gmat smoke visualize

test:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 -m unittest discover -s providers/gmat/tests -p 'test_*.py'

demo:
	./scripts/demo.sh

gmat:
	./scripts/run-gmat.sh

smoke:
	./scripts/smoke-test.sh

visualize:
	python3 -m http.server 8080 -d docs/visualization
