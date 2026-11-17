"""Host-only C ABI bindings; no Python or NumPy dependency enters the flight archive."""
from __future__ import annotations

import ctypes as C
from functools import lru_cache
from pathlib import Path


class Request(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in ("now", "deadline", "authority_until")] + [
        (name, C.c_uint32) for name in ("runtime_ms", "cpus", "ram", "reserve")] + [
        ("thermal", C.c_int32)] + [(name, C.c_uint32) for name in ("authority_mode", "connected", "allowed")]


class Candidate(C.Structure):
    _fields_ = [("window", C.c_uint64), ("valid", C.c_uint64)] + [
        (name, C.c_uint32) for name in ("cpus", "ram", "soc")] + [("thermal", C.c_int32)] + [
        (name, C.c_uint32) for name in ("migration", "local", "busy", "accelerator")]


class Decision(C.Structure):
    _fields_ = [("action", C.c_uint32), ("selected", C.c_uint32), ("rejected", C.c_uint32 * 16), ("margin", C.c_int32)]


class CgState(C.Structure):
    _fields_ = [(name, C.POINTER(C.c_double)) for name in ("x", "r", "p", "ap")] + [
        ("dimension", C.c_uint32), ("iteration", C.c_uint32)] + [
        (name, C.c_double) for name in ("rr", "bnorm2", "tolerance")]


@lru_cache
def library():
    path = Path(__file__).resolve().parents[1] / "flight/build/liboslurm_flight_host.so"
    if not path.is_file():
        raise RuntimeError("C++ host library not built; run make flight-test")
    lib = C.CDLL(str(path))
    lib.oslurm_decide.argtypes = [C.POINTER(Request), C.POINTER(Candidate), C.c_uint32]
    lib.oslurm_decide.restype = Decision
    lib.oslurm_cg_advance.argtypes = [C.POINTER(CgState), C.c_uint32]
    lib.oslurm_cg_advance.restype = C.c_int
    return lib


def advance_cg(solver, iterations):
    import numpy as np
    if not 0 <= iterations <= 2**32 - 1 or solver.dimension > 1048576 or solver.iteration + iterations >= 2**32:
        raise ValueError("C++ iteration/dimension bounds exceeded")
    ap = np.empty_like(solver.x)
    vectors = [solver.x, solver.r, solver.p, ap]
    if any(a.dtype != np.float64 or not a.flags.c_contiguous for a in vectors):
        raise ValueError("C++ CG requires contiguous float64 storage")
    state = CgState(*(a.ctypes.data_as(C.POINTER(C.c_double)) for a in vectors),
                    solver.dimension, solver.iteration, solver.rr, float(solver.bnorm ** 2), solver.tolerance)
    remaining = iterations
    while True:
        quantum = min(256, remaining)
        if library().oslurm_cg_advance(C.byref(state), quantum):
            raise ArithmeticError("C++ CG rejected invalid/numerically unsafe state")
        remaining -= quantum
        if not remaining or state.rr / state.bnorm2 <= state.tolerance ** 2:
            break
    solver.iteration, solver.rr = state.iteration, state.rr
