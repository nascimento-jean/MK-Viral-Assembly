# Install the MK-Viral-Assembly WebTool

The WebTool is the recommended option for laboratory and public-health professionals who have little or no bioinformatics experience. It provides a graphical interface for the local MK-Viral-Assembly pipeline. FASTQ files, references, databases and results remain on the computer.

Choose the instructions for your operating system:

- [Windows 10/11](#windows-1011)
- [Ubuntu 2204-or-2404](#ubuntu-2204-or-2404)

A command-line installation for servers and HPC systems is documented in the [main README](../README.md#requirements).


## Metadata template

Download a template beside the WebTool **Metadata** field (XLSX, CSV, or TSV); on Ubuntu it is saved under `~/Downloads`, or use `assets/template_metadata.*` from the repository. Fill one row per sample and keep the column headings unchanged. `Código Amostra` must match the sample name in the FASTQ/samplesheet. For Dengue, use `Sorotipo` DENV1–DENV4 when known; for RSV, use `Subtipo` A or B and reserve `Genótipo` for the detailed lineage. The tool cross-checks these values against Nextclade/BLAST and flags conflicts before creating the GISAID spreadsheet.

## Before installing

Recommended resources:

- a 64-bit x86 computer;
- 16 GB RAM or more (8 GB is the minimum for small analyses);
- an internet connection during initial setup and the first analysis;
- at least 30 GB free for the application, isolated environments and working files;
- additional space for FASTQs, results and optional databases.

The first launch can take several minutes because the application downloads the tagged MK-Viral-Assembly release and prepares isolated Nextflow, Java, Node.js and Conda environments.

## Windows 10/11

Windows 10 version 2004 or newer, or Windows 11, is required.

### Install

1. [Download `MK-Viral-Assembly-Setup.exe` directly](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest/download/MK-Viral-Assembly-Setup.exe).
2. The optional [`.sha256` verification file](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest/download/MK-Viral-Assembly-Setup.exe.sha256) is only needed to verify download integrity.
3. Optionally verify the download in PowerShell:

   ```powershell
   cd $HOME\Downloads
   (Get-FileHash .\MK-Viral-Assembly-Setup.exe -Algorithm SHA256).Hash.ToLower()
   Get-Content .\MK-Viral-Assembly-Setup.exe.sha256
   ```

   The two hashes must be identical.

4. Double-click `MK-Viral-Assembly-Setup.exe` and complete the installer.
5. Leave **Open MK-Viral-Assembly** selected.
6. On first launch, approve the Windows administrator prompt only if WSL 2 and Ubuntu need to be enabled.
7. If Windows requests a restart, restart the computer and open **MK-Viral-Assembly** from the Start menu. Setup resumes automatically.
8. Wait for the preparation window to finish. The WebTool then opens as an application window.

The installer is not currently code-signed. Windows SmartScreen may show **Unknown publisher**. Verify the SHA-256 checksum, select **More info**, and then **Run anyway**.

The Windows launcher installs WSL 2 and Ubuntu only when necessary. It creates the project and isolated environments inside Ubuntu and does not replace an existing Conda installation.

### Windows diagnostics

The launcher log is stored at:

```text
%LOCALAPPDATA%\MK-Viral-Assembly\launcher.log
```

Use the tray icon to reopen the interface or view the log.

## Ubuntu 22.04 or 24.04

The desktop package supports Ubuntu 22.04 and 24.04 on x86-64/AMD64 computers.

### Install with the graphical application center

1. [Download `MK-Viral-Assembly-WebTool_1.2.5_amd64.deb` directly](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/download/v1.2.5/MK-Viral-Assembly-WebTool_1.2.5_amd64.deb).
2. The matching [`.sha256` verification file](https://github.com/nascimento-jean/MK-Viral-Assembly/releases/download/v1.2.5/MK-Viral-Assembly-WebTool_1.2.5_amd64.deb.sha256) is optional.
3. Open the downloaded `.deb` file with **App Center** or **Software Install**.
4. Select **Install** and enter your Ubuntu password.
5. Open the applications menu, search for **MK-Viral-Assembly**, and start it.
6. Select **Continue** in the first-installation dialog and wait for setup to finish.

After setup, the WebTool opens in its own **MK-Viral-Assembly** window without browser tabs, an address bar or other browser controls. The package automatically installs the required WebKit graphical component.

### Install from a terminal

If the graphical application center does not open the package, run:

```bash
cd ~/Downloads
sha256sum -c MK-Viral-Assembly-WebTool_1.2.5_amd64.deb.sha256
sudo apt install ./MK-Viral-Assembly-WebTool_1.2.5_amd64.deb
```

Then open **MK-Viral-Assembly** from the applications menu. The `apt install ./...` command also installs the graphical and system dependencies required by the application.

If version 1.2.5 is already installed and you need to replace an earlier edition of the same package file, run:

```bash
cd ~/Downloads
sudo apt install --reinstall ./MK-Viral-Assembly-WebTool_1.2.5_amd64.deb
```

The package installs only a desktop launcher, icon and bootstrap script under system directories. On first launch, the application creates its isolated runtime in your home directory:

```text
~/.local/share/mk-viral-assembly/
├── source/
├── miniforge3/
└── envs/
```

Logs are written to:

```text
~/.local/state/mk-viral-assembly/
```

### Ubuntu diagnostics

Run these commands in a terminal:

```bash
mk-viral-assembly --diagnose
mk-viral-assembly --stop
```

The first command reports the installed paths and whether the local services are ready. The second stops the local WebTool service.

## Run an analysis

1. Open **MK-Viral-Assembly**.
2. Select **Single Analysis** for one virus/reference or **Mixed Virus Analysis** for a samplesheet with multiple viruses.
3. Use the folder and file buttons to select FASTQs, a reference FASTA, optional GFF3/primer BED files, and an output directory.
4. Choose the desired optional analyses.
5. Select **Start analysis** and keep the computer and application running until completion.
6. Open the generated dashboard and MultiQC report from the result directory.

## Kraken2, BLAST and Nextclade data

- **Kraken2:** its database is not downloaded automatically. Download or prepare a compatible Kraken2 database separately and select that directory in the WebTool.
- **BLAST:** when **BLAST identification** is enabled, the pipeline automatically downloads and builds the RefSeq Viral database on first use. It stores the database under the installed project and reuses it on later analyses. By default, it checks the database age on each run and rebuilds it after seven days.
- **Nextclade:** required datasets are obtained according to the selected dataset/virus configuration.

The first BLAST or Nextclade-enabled run can take longer and requires internet access.

## Data, privacy and removal

The WebTool listens only on `127.0.0.1`. It passes local paths to Nextflow and does not upload FASTQs, references or results.

Uninstalling the Windows launcher or Ubuntu package preserves application data, analysis history, downloaded databases and results to prevent accidental scientific-data loss. Back up important results and remove those directories manually only when you are certain they are no longer needed.

To remove the Ubuntu launcher:

```bash
sudo apt remove mk-viral-assembly-webtool
```

## Troubleshooting

- **Restart required on Windows:** restart Windows and open the application again.
- **First setup fails:** confirm the internet connection and free storage, then reopen the application. It resumes completed steps.
- **Institutional proxy or firewall:** allow GitHub, conda-forge, Bioconda, NCBI and registries used by the selected pipeline profile.
- **Folder picker opens behind the application:** update to the latest release. The current launchers request native dialogs in the foreground.
- **“The service exited before starting” after a Windows update:** reinstall the latest 1.2.5 installer. The current launcher stops stale WebTool instances before starting the corrected local service.
- **Ubuntu package reports an unsupported architecture:** the current package supports AMD64/x86-64, not ARM64.
- **WebTool does not open on Ubuntu:** confirm that the `.deb` was installed with `apt`, run `mk-viral-assembly --diagnose`, and inspect `~/.local/state/mk-viral-assembly/launcher.log` and `webtool-service.log`.
- **Version 1.2.0 still says setup is running after completion:** install version 1.2.5 or newer. Sign out of Ubuntu and sign in once to stop the old process, then open the application once.
- **Insufficient storage:** FASTQs, Nextflow work directories and databases are usually the largest items.
