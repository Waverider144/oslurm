"""Structured flight recorder and profiling support for O-SLURM."""

from .recorder import FlightRecorder, ProfilingConfig
from .schema import TRACE_SCHEMA_VERSION, TraceCategory, TraceEventType

__all__ = [
    "FlightRecorder",
    "ProfilingConfig",
    "TRACE_SCHEMA_VERSION",
    "TraceCategory",
    "TraceEventType",
]
