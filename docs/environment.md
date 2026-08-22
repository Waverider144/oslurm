# Environment Discovery

Generated at: 2026-08-21T08:54:30+08:00

## System
Linux ngphpc-ThinkPad-P14s-Gen-5 7.0.0-29-generic #29~24.04.2-Ubuntu SMP PREEMPT_DYNAMIC Wed Aug 12 17:25:56 UTC 2 x86_64 x86_64 x86_64 GNU/Linux

PRETTY_NAME="Ubuntu 24.04.4 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.4 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo

## Toolchain
Python 3.13.11
pip 25.3 from /home/ngphpc/miniconda3/lib/python3.13/site-packages/pip (python 3.13)
gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
Copyright (C) 2023 Free Software Foundation, Inc.
This is free software; see the source for copying conditions.  There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
Copyright (C) 2023 Free Software Foundation, Inc.
This is free software; see the source for copying conditions.  There is NO
warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

Ubuntu clang version 18.1.3 (1ubuntu1)
Target: x86_64-pc-linux-gnu
Thread model: posix
InstalledDir: /usr/bin
cmake version 3.28.3

CMake suite maintained and supported by Kitware (kitware.com/cmake).
GNU Make 4.3
Built for x86_64-pc-linux-gnu
Copyright (C) 1988-2020 Free Software Foundation, Inc.
License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.

## Slurm
/usr/bin/sinfo
/usr/bin/sbatch
/usr/bin/squeue
/usr/bin/sacct

## GMAT
/home/ngphpc/SDKs/eigen-master/doc/CustomizingEigen_InheritingMatrix.dox
/home/ngphpc/SDKs/VTK-9.6.2/lib/libvtkImagingMath-9.6.so.1
/home/ngphpc/SDKs/VTK-9.6.2/lib/libvtkImagingMath-9.6.so.9.6
/home/ngphpc/SDKs/VTK-9.6.2/lib/libvtkImagingMath-9.6.so

## Containers
Docker version 29.1.3, build 29.1.3-0ubuntu3~24.04.2

## Conclusions

- Slurm installed: partial client commands only.
- Slurm version: unavailable from controller; `sinfo --version` cannot complete because no config source/controller is reachable.
- Local Slurm cluster: not detected.
- GMAT installed: not detected.
- GMAT Python API importable: no (`gmat` and `GMAT` module specs are absent).
- GMAT CLI/console runner: not detected.
- Rust toolchain: not detected (`rustc` and `cargo` missing).
- Container runtime: Docker CLI is present, but Compose plugin is not available through `docker compose`.
- Attempted installation: `sudo apt-get update && sudo apt-get install -y slurm-wlm cargo` was blocked because sudo requires an interactive password.
