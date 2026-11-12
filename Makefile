.PHONY: test demo gmat smoke visualize satellite-demo profile-smoke orbit-axb test-visualization joint-demo joint-axb

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

orbit-axb:
	python3 -m oslurm.orbit_benchmark --backend local --publish

joint-demo:
	python3 -m oslurm.cli < benchmarks/joint-lifecycle.cli

joint-axb:
	python3 -m oslurm.joint_execution --backend local

test-visualization:
	node --check docs/visualization/app.js
	node --check docs/visualization/comm-overlay.js
	node tests/test_execution_replay.cjs
	node --check docs/visualization/ground-track.js
	node tests/test_ground_track.cjs
