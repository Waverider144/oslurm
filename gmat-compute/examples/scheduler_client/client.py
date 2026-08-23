from __future__ import annotations


class ComputeSimulationClient:
    def list_nodes(self):
        return ["sat001", "sat002", "sat003", "sat004"]

    def get_state(self, node):
        return {"node_id": node, "throughput_units_per_s": 480.0}

    def get_forecast(self, node, horizon=600):
        return {"node_id": node, "horizon_s": horizon, "intervals": []}

    def place_task(self, task, node):
        return {"accepted": True, "task_id": task["id"], "node_id": node}


sim = ComputeSimulationClient()
nodes = sim.list_nodes()
for node in nodes:
    state = sim.get_state(node)
    forecast = sim.get_forecast(node, horizon=600)

task = {"id": "demo-inference-001", "required_compute_units": 160000}
placement = sim.place_task(task, node="sat002")
print(placement)
