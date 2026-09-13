"""Instrumentación de run_metadata: llamadas a LLM, costo en MXN y tiempo de pared."""

import time


class RunMetrics:
    def __init__(self):
        self.llm_calls = 0
        self.mxn_cost = 0.0
        self.cost_by_role: dict[str, float] = {}
        self.start_time: float | None = None

    def start(self) -> None:
        self.start_time = time.monotonic()

    def record_llm_call(self, role: str, cost_mxn: float) -> None:
        self.llm_calls += 1
        self.mxn_cost += cost_mxn
        self.cost_by_role[role] = self.cost_by_role.get(role, 0.0) + cost_mxn

    def finalize(self) -> dict:
        if self.start_time is None:
            raise RuntimeError("RunMetrics.start() no se llamó al inicio de la corrida")
        return {
            "llm_calls": self.llm_calls,
            "mxn_cost": round(self.mxn_cost, 2),
            "wall_clock_seconds": round(time.monotonic() - self.start_time, 2),
            "cost_by_role": {k: round(v, 2) for k, v in sorted(self.cost_by_role.items())},
            # Sin LLM en ninguna parte del camino: reglas SQL, ensamblador y plantillas.
            "deterministic": self.llm_calls == 0,
        }
