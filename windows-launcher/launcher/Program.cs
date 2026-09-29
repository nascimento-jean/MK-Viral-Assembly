using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.Json;

namespace MkViralAssembly.WindowsLauncher;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length > 0 && args[0].Equals("--diagnose", StringComparison.OrdinalIgnoreCase))
        {
            var report = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(), "mkva-launcher-diagnostic.json");
            Environment.ExitCode = Diagnostics.WriteAsync(report, startService: false).GetAwaiter().GetResult();
            return;
        }

        if (args.Length > 0 && args[0].Equals("--test-start", StringComparison.OrdinalIgnoreCase))
        {
            var report = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(), "mkva-launcher-start-test.json");
            Environment.ExitCode = Diagnostics.WriteAsync(report, startService: true).GetAwaiter().GetResult();
            return;
        }

        ApplicationConfiguration.Initialize();
        Application.Run(new LauncherContext());
    }
}

internal sealed record WslTarget(string Distro, string ProjectPath);

internal sealed class LauncherEngine : IDisposable
{
    private static readonly HttpClient Http = new(new HttpClientHandler { UseProxy = false })
    {
        Timeout = TimeSpan.FromSeconds(2)
    };

    private readonly object _logLock = new();
    private Process? _wslProcess;
    private readonly string _dataDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "MK-Viral-Assembly");

    private const string ReleaseRef = "v1.2.2";
    public event Action<string>? Message;
    public string LogPath => Path.Combine(_dataDir, "launcher.log");
    public WslTarget? Target { get; private set; }
    public bool StartedByLauncher => _wslProcess is { HasExited: false };

    public async Task<WslTarget> DetectAsync(CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(_dataDir);
        var configured = LoadConfiguration();
        if (configured is not null && await ProbeTargetAsync(configured, cancellationToken))
        {
            Target = configured;
            return configured;
        }

        Message?.Invoke("Localizando o projeto no WSL...");
        var distros = await ListDistributionsAsync(cancellationToken);
        foreach (var distro in distros)
        {
            var command = "for p in \"$HOME/MK-Viral-Assembly\" /home/*/MK-Viral-Assembly /mnt/d/MK-Viral-Assembly; do " +
                          "if [ -x \"$p/webtool/start-local.sh\" ] && [ -f \"$p/main.nf\" ]; then printf '%s' \"$p\"; exit 0; fi; done; exit 4";
            var result = await RunWslCaptureAsync(distro, command, cancellationToken);
            var project = result.Output.Trim();
            if (result.ExitCode == 0 && project.Length > 0)
            {
                var target = new WslTarget(distro, project);
                SaveConfiguration(target);
                Target = target;
                return target;
            }
        }

        throw new InvalidOperationException(
            "Não encontrei ~/MK-Viral-Assembly no WSL. Extraia o projeto na pasta pessoal do Ubuntu e tente novamente.");
    }

    public async Task<WslTarget> DetectOrInstallAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            return await DetectAsync(cancellationToken);
        }
        catch (InvalidOperationException)
        {
            return await InstallEnvironmentAsync(cancellationToken);
        }
    }

    private async Task<WslTarget> InstallEnvironmentAsync(CancellationToken cancellationToken)
    {
        Message?.Invoke("Preparando o ambiente da primeira instalação...");
        List<string> distros;
        try { distros = await ListDistributionsAsync(cancellationToken); }
        catch { distros = new List<string>(); }

        var installedDistroNow = false;
        if (distros.Count == 0)
        {
            Message?.Invoke("Instalando WSL 2 e Ubuntu. Autorize a janela do Windows...");
            await InstallWslAsync(cancellationToken);
            installedDistroNow = true;
            try { distros = await ListDistributionsAsync(cancellationToken); }
            catch { distros = new List<string>(); }
            if (distros.Count == 0)
            {
                throw new InvalidOperationException(
                    "O Windows precisa ser reiniciado para concluir o WSL. Reinicie o computador e abra novamente o MK-Viral-Assembly.");
            }
        }

        var distro = distros.FirstOrDefault(value => value.Equals("Ubuntu-22.04", StringComparison.OrdinalIgnoreCase))
                     ?? distros.FirstOrDefault(value => value.StartsWith("Ubuntu", StringComparison.OrdinalIgnoreCase))
                     ?? distros[0];
        if (installedDistroNow)
        {
            Message?.Invoke("Configurando o usuário isolado da aplicação...");
            var initialize = await RunWslCaptureAsync(
                distro,
                "id -u mkva >/dev/null 2>&1 || useradd -m -s /bin/bash mkva; printf '[user]\ndefault=mkva\n' > /etc/wsl.conf",
                cancellationToken,
                "root");
            if (initialize.ExitCode != 0)
                throw new InvalidOperationException("Não foi possível inicializar o usuário Linux da aplicação. " + initialize.Output.Trim());
            await TerminateDistroAsync(distro, cancellationToken);
        }

        var bootstrapPath = Path.Combine(AppContext.BaseDirectory, "bootstrap-wsl.sh");
        if (!File.Exists(bootstrapPath))
            throw new InvalidOperationException("O instalador está incompleto: bootstrap-wsl.sh não foi encontrado.");

        Message?.Invoke("Baixando e configurando a WebTool. Isso pode levar vários minutos...");
        var script = await File.ReadAllTextAsync(bootstrapPath, cancellationToken);
        var encoded = Convert.ToBase64String(Encoding.UTF8.GetBytes(script));
        var shellCommand = $"export MKVA_RELEASE_REF={ShellQuote(ReleaseRef)}; printf '%s' '{encoded}' | base64 -d | bash";
        var result = await RunWslStreamingAsync(distro, shellCommand, cancellationToken);
        AppendLog(result.Output);
        if (result.ExitCode != 0)
        {
            var detail = result.Output.Split('\n', StringSplitOptions.RemoveEmptyEntries).LastOrDefault()?.Trim();
            throw new InvalidOperationException("Não foi possível preparar o ambiente WSL. " +
                (string.IsNullOrWhiteSpace(detail) ? $"Consulte {LogPath}" : detail));
        }

        var targetPath = result.Output.Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .FirstOrDefault(line => line.StartsWith("MKVA_TARGET=", StringComparison.Ordinal))?
            .Substring("MKVA_TARGET=".Length).Trim();
        if (string.IsNullOrWhiteSpace(targetPath))
            throw new InvalidOperationException("A instalação terminou sem informar o diretório do projeto.");

        var target = new WslTarget(distro, targetPath);
        SaveConfiguration(target);
        Target = target;
        return target;
    }

    private static async Task InstallWslAsync(CancellationToken cancellationToken)
    {
        var info = new ProcessStartInfo("wsl.exe")
        {
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Normal
        };
        info.ArgumentList.Add("--install");
        info.ArgumentList.Add("-d");
        info.ArgumentList.Add("Ubuntu-22.04");
        info.ArgumentList.Add("--no-launch");
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Não foi possível iniciar a instalação do WSL.");
        await process.WaitForExitAsync(cancellationToken);
        if (process.ExitCode != 0 && process.ExitCode != 3010)
            throw new InvalidOperationException($"A instalação do WSL terminou com o código {process.ExitCode}.");
    }

    public async Task<bool> EnsureStartedAsync(CancellationToken cancellationToken = default)
    {
        if (await IsReadyAsync(cancellationToken))
        {
            Message?.Invoke("A webtool já está em execução.");
            return true;
        }

        var target = Target ?? await DetectAsync(cancellationToken);
        Message?.Invoke($"Iniciando {target.Distro} silenciosamente...");
        StartWsl(target);

        var deadline = DateTime.UtcNow.AddMinutes(2);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (_wslProcess?.HasExited == true)
            {
                throw new InvalidOperationException(
                    $"O serviço encerrou antes de iniciar. Consulte o log em {LogPath}");
            }

            if (await IsReadyAsync(cancellationToken))
            {
                Message?.Invoke("Webtool pronta.");
                return true;
            }

            await Task.Delay(1500, cancellationToken);
        }

        throw new TimeoutException($"A webtool não ficou pronta em dois minutos. Consulte {LogPath}");
    }

    public static async Task<bool> IsReadyAsync(CancellationToken cancellationToken = default)
    {
        return await ReturnsSuccessAsync("http://127.0.0.1:8787/api/health", cancellationToken) &&
               await ReturnsSuccessAsync("http://127.0.0.1:3000/", cancellationToken);
    }

    public void OpenApplication()
    {
        var edgeCandidates = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft", "Edge", "Application", "msedge.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft", "Edge", "Application", "msedge.exe")
        };
        var edge = edgeCandidates.FirstOrDefault(File.Exists);
        if (edge is not null)
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = edge,
                Arguments = "--app=http://localhost:3000 --new-window",
                UseShellExecute = true
            });
            return;
        }

        Process.Start(new ProcessStartInfo("http://localhost:3000") { UseShellExecute = true });
    }

    public void OpenLog()
    {
        Directory.CreateDirectory(_dataDir);
        if (!File.Exists(LogPath)) File.WriteAllText(LogPath, "Nenhuma mensagem registrada.\r\n");
        Process.Start(new ProcessStartInfo(LogPath) { UseShellExecute = true });
    }

    public async Task StopStartedServiceAsync()
    {
        if (_wslProcess is null || _wslProcess.HasExited) return;
        Message?.Invoke("Encerrando os serviços iniciados pelo aplicativo...");
        try
        {
            _wslProcess.Kill(entireProcessTree: true);
            await _wslProcess.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));
        }
        catch (Exception ex)
        {
            AppendLog("Falha ao encerrar: " + ex.Message);
        }
    }

    public void Dispose()
    {
        _wslProcess?.Dispose();
    }

    private void StartWsl(WslTarget target)
    {
        var project = ShellQuote(target.ProjectPath);
        var command = $"set -e; PROJECT={project}; cd \"$PROJECT/webtool\"; " +
                      "BASE=''; for b in \"$HOME/miniconda3\" \"$HOME/anaconda3\" \"$HOME/miniforge3\" \"$HOME/mambaforge\"; do " +
                      "if [ -x \"$b/envs/mkva-webtool/bin/npm\" ]; then BASE=\"$b\"; break; fi; done; " +
                      "if [ -z \"$BASE\" ] && command -v conda >/dev/null 2>&1; then BASE=\"$(conda info --base)\"; fi; " +
                      "[ -n \"$BASE\" ] || { echo 'Miniconda/Conda não encontrado.' >&2; exit 21; }; " +
                      "export MKVA_NODE_ENV_BIN=\"$BASE/envs/mkva-webtool/bin\"; " +
                      "if [ -x \"$BASE/envs/nextflow/bin/nextflow\" ]; then export MKVA_NEXTFLOW=\"$BASE/envs/nextflow/bin/nextflow\"; " +
                      "elif command -v nextflow >/dev/null 2>&1; then export MKVA_NEXTFLOW=\"$(command -v nextflow)\"; " +
                      "else echo 'Nextflow não encontrado.' >&2; exit 22; fi; " +
                      "if [ -x \"$BASE/envs/nextflow/bin/java\" ]; then export MKVA_JAVA=\"$BASE/envs/nextflow/bin/java\"; " +
                      "elif command -v java >/dev/null 2>&1; then export MKVA_JAVA=\"$(command -v java)\"; fi; " +
                      "if [ -f \"$PROJECT/.mkva-managed-install\" ]; then export MKVA_DEFAULT_PROFILE=conda; fi; " +
                      "exec ./start-local.sh";

        var info = new ProcessStartInfo("wsl.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        info.ArgumentList.Add("-d");
        info.ArgumentList.Add(target.Distro);
        info.ArgumentList.Add("--");
        info.ArgumentList.Add("bash");
        info.ArgumentList.Add("-lc");
        info.ArgumentList.Add(WrapShellCommand(command));

        _wslProcess = new Process { StartInfo = info, EnableRaisingEvents = true };
        _wslProcess.OutputDataReceived += (_, e) => { if (e.Data is not null) AppendLog(e.Data); };
        _wslProcess.ErrorDataReceived += (_, e) => { if (e.Data is not null) AppendLog("ERRO: " + e.Data); };
        _wslProcess.Exited += (_, _) => AppendLog($"Processo WSL encerrado com código {_wslProcess.ExitCode}.");
        _wslProcess.Start();
        _wslProcess.BeginOutputReadLine();
        _wslProcess.BeginErrorReadLine();
        AppendLog($"Iniciado em {DateTime.Now:yyyy-MM-dd HH:mm:ss}: {target.Distro} {target.ProjectPath}");
    }

    private async Task<bool> ProbeTargetAsync(WslTarget target, CancellationToken cancellationToken)
    {
        var project = ShellQuote(target.ProjectPath);
        var result = await RunWslCaptureAsync(
            target.Distro,
            $"test -x {project}/webtool/start-local.sh && test -f {project}/main.nf",
            cancellationToken);
        return result.ExitCode == 0;
    }

    private static async Task<List<string>> ListDistributionsAsync(CancellationToken cancellationToken)
    {
        var info = new ProcessStartInfo("wsl.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.Unicode
        };
        info.ArgumentList.Add("-l");
        info.ArgumentList.Add("-q");
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Não foi possível iniciar wsl.exe.");
        var output = await process.StandardOutput.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        if (process.ExitCode != 0) throw new InvalidOperationException("WSL não está instalado ou não possui uma distribuição Linux.");
        return output.Replace("\0", "")
            .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(value => value.Trim())
            .Where(value => value.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static async Task<(int ExitCode, string Output)> RunWslCaptureAsync(
        string distro,
        string shellCommand,
        CancellationToken cancellationToken,
        string? user = null)
    {
        var info = new ProcessStartInfo("wsl.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        info.ArgumentList.Add("-d");
        info.ArgumentList.Add(distro);
        if (!string.IsNullOrWhiteSpace(user))
        {
            info.ArgumentList.Add("-u");
            info.ArgumentList.Add(user);
        }
        info.ArgumentList.Add("--");
        info.ArgumentList.Add("bash");
        info.ArgumentList.Add("-lc");
        info.ArgumentList.Add(WrapShellCommand(shellCommand));
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Não foi possível consultar o WSL.");
        var outputTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var errorTask = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        var output = await outputTask;
        var error = await errorTask;
        return (process.ExitCode, output.Length > 0 ? output : error);
    }

    private async Task<(int ExitCode, string Output)> RunWslStreamingAsync(
        string distro,
        string shellCommand,
        CancellationToken cancellationToken)
    {
        var info = new ProcessStartInfo("wsl.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        info.ArgumentList.Add("-d");
        info.ArgumentList.Add(distro);
        info.ArgumentList.Add("--");
        info.ArgumentList.Add("bash");
        info.ArgumentList.Add("-lc");
        info.ArgumentList.Add(WrapShellCommand(shellCommand));

        var output = new StringBuilder();
        var gate = new object();
        using var process = new Process { StartInfo = info };
        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            lock (gate) output.AppendLine(e.Data);
            if (e.Data.StartsWith("STATUS:", StringComparison.Ordinal))
                Message?.Invoke(e.Data.Substring("STATUS:".Length).Trim());
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            lock (gate) output.AppendLine("ERRO: " + e.Data);
        };
        if (!process.Start()) throw new InvalidOperationException("Não foi possível iniciar a preparação do WSL.");
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await process.WaitForExitAsync(cancellationToken);
        process.WaitForExit();
        lock (gate) return (process.ExitCode, output.ToString());
    }

    private static async Task TerminateDistroAsync(string distro, CancellationToken cancellationToken)
    {
        var info = new ProcessStartInfo("wsl.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true
        };
        info.ArgumentList.Add("--terminate");
        info.ArgumentList.Add(distro);
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Não foi possível reiniciar a distribuição WSL.");
        await process.WaitForExitAsync(cancellationToken);
    }

    private static async Task<bool> ReturnsSuccessAsync(string url, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await Http.GetAsync(url, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private WslTarget? LoadConfiguration()
    {
        var path = Path.Combine(_dataDir, "launcher.conf");
        if (!File.Exists(path)) return null;
        var values = File.ReadAllLines(path)
            .Select(line => line.Split('=', 2))
            .Where(parts => parts.Length == 2)
            .ToDictionary(parts => parts[0].Trim(), parts => parts[1].Trim(), StringComparer.OrdinalIgnoreCase);
        return values.TryGetValue("distro", out var distro) && values.TryGetValue("project", out var project)
            ? new WslTarget(distro, project)
            : null;
    }

    private void SaveConfiguration(WslTarget target)
    {
        Directory.CreateDirectory(_dataDir);
        File.WriteAllLines(Path.Combine(_dataDir, "launcher.conf"), new[]
        {
            $"distro={target.Distro}",
            $"project={target.ProjectPath}"
        });
    }

    private void AppendLog(string message)
    {
        lock (_logLock)
        {
            Directory.CreateDirectory(_dataDir);
            File.AppendAllText(LogPath, $"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");
        }
    }

    private static string WrapShellCommand(string command)
    {
        var encoded = Convert.ToBase64String(Encoding.UTF8.GetBytes(command));
        return "printf '%s' '" + encoded + "' | base64 -d | bash";
    }
    private static string ShellQuote(string value) => "'" + value.Replace("'", "'\\''") + "'";
}

internal sealed class LauncherContext : ApplicationContext
{
    private readonly LauncherEngine _engine = new();
    private readonly LauncherForm _form;
    private readonly NotifyIcon _tray;
    private readonly CancellationTokenSource _cancellation = new();
    private bool _exiting;

    public LauncherContext()
    {
        _form = new LauncherForm();
        _engine.Message += message => _form.SetStatus(message);
        _form.OpenRequested += (_, _) => _engine.OpenApplication();
        _form.LogRequested += (_, _) => _engine.OpenLog();
        _form.StopRequested += async (_, _) => await StopAsync();
        _form.FormClosing += OnFormClosing;

        var menu = new ContextMenuStrip();
        menu.Items.Add("Abrir MK-Viral-Assembly", null, (_, _) => ShowForm());
        menu.Items.Add("Abrir interface", null, (_, _) => _engine.OpenApplication());
        menu.Items.Add("Parar serviços", null, async (_, _) => await StopAsync());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Sair do launcher", null, (_, _) => ExitLauncher());

        _tray = new NotifyIcon
        {
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application,
            Text = "MK-Viral-Assembly",
            Visible = true,
            ContextMenuStrip = menu
        };
        _tray.DoubleClick += (_, _) => ShowForm();
        _form.Shown += async (_, _) => await StartAsync();
        _form.Show();
    }

    private async Task StartAsync()
    {
        try
        {
            var target = await _engine.DetectOrInstallAsync(_cancellation.Token);
            _form.SetEnvironment($"{target.Distro} · {target.ProjectPath}");
            await _engine.EnsureStartedAsync(_cancellation.Token);
            _form.SetReady();
            _tray.Text = "MK-Viral-Assembly · pronta";
            _engine.OpenApplication();
            _form.Hide();
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            _form.SetError(ex.Message);
            _tray.Text = "MK-Viral-Assembly · atenção necessária";
        }
    }

    private async Task StopAsync()
    {
        await _engine.StopStartedServiceAsync();
        _form.SetStopped();
        ShowForm();
    }

    private void ShowForm()
    {
        _form.Show();
        _form.WindowState = FormWindowState.Normal;
        _form.Activate();
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs e)
    {
        if (_exiting) return;
        e.Cancel = true;
        _form.Hide();
        _tray.ShowBalloonTip(2500, "MK-Viral-Assembly", "O launcher continua ativo próximo ao relógio.", ToolTipIcon.Info);
    }

    private void ExitLauncher()
    {
        _exiting = true;
        _cancellation.Cancel();
        _tray.Visible = false;
        _tray.Dispose();
        _engine.Dispose();
        _form.Close();
        ExitThread();
    }
}

internal sealed class LauncherForm : Form
{
    private readonly Label _status = new();
    private readonly Label _environment = new();
    private readonly ProgressBar _progress = new();
    private readonly Button _open = new();
    private readonly Button _stop = new();
    private readonly Button _log = new();

    public event EventHandler? OpenRequested;
    public event EventHandler? StopRequested;
    public event EventHandler? LogRequested;

    public LauncherForm()
    {
        Text = "MK-Viral-Assembly";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(620, 370);
        MinimumSize = new Size(620, 370);
        BackColor = Color.FromArgb(244, 248, 249);
        Font = new Font("Segoe UI", 10F);

        var header = new Panel { Dock = DockStyle.Top, Height = 142, BackColor = Color.FromArgb(5, 37, 54) };
        var brand = new Label
        {
            Text = "MK-VIRAL-ASSEMBLY",
            ForeColor = Color.White,
            Font = new Font("Segoe UI Semibold", 21F, FontStyle.Bold),
            AutoSize = true,
            Location = new Point(35, 27)
        };
        var subtitle = new Label
        {
            Text = "Instalação guiada e análise viral local pelo Windows",
            ForeColor = Color.FromArgb(120, 218, 210),
            Font = new Font("Segoe UI", 9.5F),
            AutoSize = true,
            Location = new Point(38, 84)
        };
        header.Controls.Add(brand);
        header.Controls.Add(subtitle);

        var caption = new Label
        {
            Text = "STATUS DO AMBIENTE",
            ForeColor = Color.FromArgb(0, 123, 119),
            Font = new Font("Segoe UI Semibold", 9F, FontStyle.Bold),
            AutoSize = true,
            Location = new Point(37, 170)
        };
        _status.Text = "Preparando a webtool...";
        _status.Font = new Font("Segoe UI Semibold", 15F, FontStyle.Bold);
        _status.ForeColor = Color.FromArgb(5, 37, 54);
        _status.AutoSize = false;
        _status.Size = new Size(545, 58);
        _status.Location = new Point(37, 195);

        _environment.Text = "Detectando ou instalando o ambiente necessário...";
        _environment.ForeColor = Color.FromArgb(91, 113, 124);
        _environment.AutoSize = false;
        _environment.Size = new Size(545, 26);
        _environment.Location = new Point(37, 245);

        _progress.Style = ProgressBarStyle.Marquee;
        _progress.MarqueeAnimationSpeed = 24;
        _progress.Location = new Point(40, 278);
        _progress.Size = new Size(540, 7);

        ConfigureButton(_open, "Abrir interface", 40, true);
        ConfigureButton(_stop, "Parar serviços", 210, false);
        ConfigureButton(_log, "Ver log", 380, false);
        _open.Enabled = false;
        _open.Click += (_, _) => OpenRequested?.Invoke(this, EventArgs.Empty);
        _stop.Click += (_, _) => StopRequested?.Invoke(this, EventArgs.Empty);
        _log.Click += (_, _) => LogRequested?.Invoke(this, EventArgs.Empty);

        Controls.Add(header);
        Controls.Add(caption);
        Controls.Add(_status);
        Controls.Add(_environment);
        Controls.Add(_progress);
        Controls.Add(_open);
        Controls.Add(_stop);
        Controls.Add(_log);
    }

    public void SetStatus(string message) => Ui(() => _status.Text = message);
    public void SetEnvironment(string text) => Ui(() => _environment.Text = text);

    public void SetReady() => Ui(() =>
    {
        _status.Text = "Webtool pronta para uso";
        _progress.Style = ProgressBarStyle.Continuous;
        _progress.Value = 100;
        _open.Enabled = true;
        _stop.Enabled = true;
    });

    public void SetError(string message) => Ui(() =>
    {
        _status.Text = message;
        _status.ForeColor = Color.FromArgb(170, 62, 39);
        _progress.Style = ProgressBarStyle.Continuous;
        _progress.Value = 0;
        _log.Enabled = true;
    });

    public void SetStopped() => Ui(() =>
    {
        _status.Text = "Serviços encerrados";
        _progress.Style = ProgressBarStyle.Continuous;
        _progress.Value = 0;
        _open.Enabled = false;
        _stop.Enabled = false;
    });

    private static void ConfigureButton(Button button, string text, int x, bool primary)
    {
        button.Text = text;
        button.Location = new Point(x, 307);
        button.Size = new Size(155, 40);
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = primary ? 0 : 1;
        button.BackColor = primary ? Color.FromArgb(0, 151, 145) : Color.White;
        button.ForeColor = primary ? Color.White : Color.FromArgb(5, 70, 82);
        button.Cursor = Cursors.Hand;
    }

    private void Ui(Action action)
    {
        if (InvokeRequired) BeginInvoke(action); else action();
    }
}

internal static class Diagnostics
{
    public static async Task<int> WriteAsync(string reportPath, bool startService)
    {
        using var engine = new LauncherEngine();
        var messages = new List<string>();
        engine.Message += messages.Add;
        try
        {
            var target = await engine.DetectAsync();
            var before = await LauncherEngine.IsReadyAsync();
            var ready = before;
            if (startService) ready = await engine.EnsureStartedAsync();
            var report = new
            {
                ok = ready || !startService,
                distro = target.Distro,
                project = target.ProjectPath,
                readyBefore = before,
                readyAfter = ready,
                startedByLauncher = engine.StartedByLauncher,
                messages,
                log = engine.LogPath
            };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath))!);
            await File.WriteAllTextAsync(reportPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
            if (startService && engine.StartedByLauncher) await engine.StopStartedServiceAsync();
            return ready || !startService ? 0 : 2;
        }
        catch (Exception ex)
        {
            var report = new { ok = false, error = ex.ToString(), messages, log = engine.LogPath };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath))!);
            await File.WriteAllTextAsync(reportPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
            return 1;
        }
    }
}
