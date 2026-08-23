# GMAT Plugin Source Area

The current implementation uses `adapters/gmat/gmat_ephemeris.py` for real GMAT
runtime integration. A compiled plugin should stay thin and adapt GMAT
spacecraft state into `OrbitalEnvironmentState`.
