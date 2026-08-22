.PHONY: test demo gmat smoke

test:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 -m unittest discover -s providers/gmat/tests -p 'test_*.py'

demo:
	./scripts/demo.sh

gmat:
	./scripts/run-gmat.sh

smoke:
	./scripts/smoke-test.sh
