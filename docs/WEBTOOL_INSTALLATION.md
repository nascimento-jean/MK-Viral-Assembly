# Installing the MK-Viral-Assembly WebTool on Windows

The Windows application is intended for laboratory and public-health professionals who do not normally use a terminal. FASTQ files and results stay on the computer; the graphical interface only controls the local Nextflow pipeline.

## Requirements

- Windows 10 version 2004 or newer, or Windows 11, on a 64-bit computer;
- permission to approve the Windows WSL installation if WSL is not already available;
- an internet connection during initial setup and the first pipeline run;
- at least 16 GB RAM recommended (8 GB minimum for small runs);
- at least 30 GB free for the application, Conda environments and working files, plus space for FASTQs, results and optional databases.

Kraken2 and BLAST databases can require substantially more storage and are not bundled with the installer.

## Recommended installation

1. Open the latest [MK-Viral-Assembly release](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest).
2. Download `MK-Viral-Assembly-Setup.exe` and its `.sha256` file.
3. Run the installer and leave **Open MK-Viral-Assembly** selected.
4. On first launch, approve the Windows administrator prompt only if WSL and Ubuntu need to be installed.
5. Wait while the application downloads the tagged MK-Viral-Assembly release and creates isolated Nextflow and WebTool environments.
6. If Windows requests a restart, restart it and open **MK-Viral-Assembly** from the Start menu. Setup resumes automatically.

The current installer is not code-signed. Windows SmartScreen may show an **Unknown publisher** warning; verify the downloaded file with the published SHA-256 checksum before choosing **More info** and **Run anyway**.

The initial preparation may take several minutes. The launcher displays its current stage and writes a diagnostic log under `%LOCALAPPDATA%\MK-Viral-Assembly\launcher.log`.

## What is installed

The Windows installer contains a self-contained launcher, so a separate .NET installation is unnecessary. The launcher prepares:

- WSL 2 with Ubuntu 22.04 when no Linux distribution exists;
- the tagged MK-Viral-Assembly source under `~/MK-Viral-Assembly`;
- an isolated Miniforge installation when Conda is unavailable;
- Nextflow and Java in the `nextflow` environment;
- Node.js and the local WebTool in the `mkva-webtool` environment.

Conda is the default execution profile on Windows. Docker and Singularity/Apptainer remain available for advanced installations.

## Data and privacy

The WebTool listens only on `127.0.0.1`. It passes local paths to Nextflow and does not upload FASTQs, references or results. Analysis history is stored in `webtool/.local-data` inside the WSL project.

Uninstalling the Windows launcher does not delete the WSL project, analysis history, FASTQs, databases or results. This prevents accidental scientific-data loss.

## Troubleshooting

Use the tray icon to open the launcher and select **View log**. Common first-installation cases are:

- **Restart required:** restart Windows and open the application again.
- **Institutional proxy or firewall:** allow access to GitHub, conda-forge, Bioconda and the registries used by the selected pipeline profile.
- **Insufficient storage:** free space before retrying; Nextflow work directories and optional databases are the largest items.
- **Existing incomplete folder:** rename the existing `~/MK-Viral-Assembly` directory and retry, or complete that installation manually.

Advanced Linux and HPC installation remains documented in the main README.
