# Environment

Collected on 2026-08-23 in `/home/ngphpc/Desktop/OSLURM`.

## OS

```text
Linux ngphpc-ThinkPad-P14s-Gen-5 7.0.0-30-generic #30~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC Fri Aug 7 13:27:52 UTC 2 x86_64 GNU/Linux
Ubuntu 24.04.4 LTS (Noble Numbat)
```

## Toolchain

```text
Python 3.13.11
pip 25.3
gcc 13.3.0
g++ 13.3.0
clang 18.1.3
cmake 3.28.3
GNU Make 4.3
```

`ccache` is installed but attempts to write to a read-only cache path in this
sandbox. GMAT-Compute disables ccache in its local `Makefile`.

## Repository State

`git status --short` in the parent repository reported no tracked changes at
the time of the environment check. The new project is created under
`gmat-compute/`.

## GMAT Runtime

Detected executable:

```text
/home/ngphpc/Desktop/OSLURM/third_party/GMAT-R2026a-fixed/bin/GmatConsole
```

Version smoke:

```text
GMAT Console Application
General Mission Analysis Tool
Build Date: Aug 22 2026 18:15:04
R2026a
```

The console initializes successfully and can run report-file scripts. Several
optional/proprietary plugins are absent, including OpenFramesInterface, but they
are not required for the current compute adapter.

## GMAT Source / Plugin Materials

Found:

```text
third_party/GMAT
third_party/GMAT-build
third_party/GMAT/plugins/CMakeLists.txt
third_party/GMAT/plugins/TLEPropagatorPlugin
third_party/GMAT/plugins/CInterfacePlugin
third_party/GMAT/plugins/EstimationPlugin
third_party/GMAT/src
```

Startup file:

```text
third_party/GMAT-R2026a-fixed/bin/gmat_startup_file.txt
```

Plugin loading uses `PLUGIN = ../plugins/<library>`. The current fixed runtime
tries to load `../plugins/libOpenFramesInterface` but the library is not present.

## Integration Decision

GMAT Plugin: PARTIAL

GMAT Runtime Integration: REAL

The first implementation uses a thin GMAT adapter that runs `GmatConsole`,
generates spacecraft ECI report data, converts it into `OrbitalEnvironmentState`,
and feeds the compute core. A GMAT plugin shell is reserved under `plugin/gmat/`.
