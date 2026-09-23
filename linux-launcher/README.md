# Ubuntu desktop package

This directory builds the Ubuntu `.deb` package for the MK-Viral-Assembly WebTool.

The package installs only a small desktop launcher, icon and bootstrap script. On first launch, the bootstrap downloads the matching tagged project release and creates isolated runtimes under:

```text
~/.local/share/mk-viral-assembly/
├── source/
├── miniforge3/
└── envs/
    ├── nextflow/
    └── mkva-webtool/
```

Logs are written under `~/.local/state/mk-viral-assembly/`. Removing the Debian package intentionally preserves this user directory, including analysis history, optional BLAST databases and any results saved there.

## Build without installing

```bash
./linux-launcher/build-deb.sh
```

The command produces a Debian package and SHA-256 sidecar under `linux-launcher/output/`. It never installs the package.

## Non-destructive checks

```bash
./linux-launcher/tests/test-linux-launcher.sh
MKVA_BOOTSTRAP_TEST=1 ./linux-launcher/bootstrap-linux.sh
MKVA_LAUNCHER_TEST=1 MKVA_PACKAGE_DIR=./linux-launcher ./linux-launcher/mkva-webtool
```

The GitHub release workflow repeats these checks and builds the package on Ubuntu.
