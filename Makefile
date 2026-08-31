.PHONY: test demo gmat smoke visualize satellite-demo profile-smoke

test:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 -m unittest discover -s providers/gmat/tests -p 'test_*.py'

demo:
	./scripts/demo.sh

satellite-demo:
	./scripts/satellite-demo.sh

gmat:
	./scripts/run-gmat.sh

smoke:
	./scripts/smoke-test.sh

visualize:
	python3 -m http.server 8081 -d docs/visualization

profile-smoke:
	printf 'profile on --mode full --run-id profile-smoke\nrun satellite-demo\nprofile summary\nprofile topology\nprofile scheduler\nprofile bottleneck constellation\nprofile failures\nprofile off\n' | python3 -m oslurm.cli
