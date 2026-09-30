using System.Diagnostics;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

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

        if (args.Length > 0 && args[0].Equals("--test-native-pickers", StringComparison.OrdinalIgnoreCase))
        {
            ApplicationConfiguration.Initialize();
            var report = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(), "mkva-native-picker-test.json");
            Environment.ExitCode = NativePickerDiagnostics.Write(report);
            return;
        }

        if (args.Length > 0 && args[0].Equals("--test-native-picker-selection", StringComparison.OrdinalIgnoreCase))
        {
            ApplicationConfiguration.Initialize();
            var report = args.Length > 1 ? args[1] : Path.Combine(Path.GetTempPath(), "mkva-native-picker-selection-test.json");
            var directory = args.Length > 2 ? args[2] : Path.GetTempPath();
            Environment.ExitCode = NativePickerDiagnostics.WriteSelection(report, directory);
            return;
        }

        ApplicationConfiguration.Initialize();
        using var activationSignal = new EventWaitHandle(
            initialState: false,
            mode: EventResetMode.AutoReset,
            name: @"Local\MK-Viral-Assembly-Activate");
        using var singleInstance = new Mutex(
            initiallyOwned: true,
            name: @"Local\MK-Viral-Assembly-Launcher",
            createdNew: out var createdNew);
        if (!createdNew)
        {
            activationSignal.Set();
            return;
        }
        Application.Run(new LauncherContext(activationSignal));
    }
}

internal sealed record WslTarget(string Distro, string ProjectPath, string User = "");

internal sealed class LauncherEngine : IDisposable
{
    private static readonly HttpClient Http = new(new HttpClientHandler { UseProxy = false })
    {
        Timeout = TimeSpan.FromSeconds(2)
    };

    private readonly object _logLock = new();
    private readonly Queue<string> _recentOutput = new();
    private Process? _wslProcess;
    private readonly string _dataDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "MK-Viral-Assembly");

    private const string ReleaseRef = "v1.2.4";
    private const string ReleaseRevision = "windows-activation-picker-2026-09-30";
    public string? PickerDirectory { get; set; }
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
            configured = await ResolveTargetUserAsync(configured, cancellationToken);
            SaveConfiguration(configured);
            Target = configured;
            return configured;
        }

        Message?.Invoke("Localizando o projeto no WSL...");
        var distros = await ListDistributionsAsync(cancellationToken);
        foreach (var distro in distros)
        {
            var command = "for p in \"$HOME/MK-Viral-Assembly\" /home/*/MK-Viral-Assembly /mnt/d/MK-Viral-Assembly; do " +
                          "if [ -x \"$p/webtool/start-local.sh\" ] && [ -f \"$p/main.nf\" ]; then " +
                          "owner=$(stat -c %U \"$p\" 2>/dev/null || id -un); printf '%s\t%s' \"$p\" \"$owner\"; exit 0; fi; done; exit 4";
            var result = await RunWslCaptureAsync(distro, command, cancellationToken);
            var parts = result.Output.Trim().Split('	', 2);
            var project = parts.ElementAtOrDefault(0) ?? string.Empty;
            var user = parts.ElementAtOrDefault(1) ?? string.Empty;
            if (result.ExitCode == 0 && project.Length > 0)
            {
                var target = new WslTarget(distro, project, user);
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
        WslTarget target;
        try
        {
            target = await DetectAsync(cancellationToken);
        }
        catch (InvalidOperationException)
        {
            return await InstallEnvironmentAsync(cancellationToken);
        }

        await UpdateManagedEnvironmentAsync(target, cancellationToken);
        return target;
    }

    private async Task UpdateManagedEnvironmentAsync(WslTarget target, CancellationToken cancellationToken)
    {
        var project = ShellQuote(target.ProjectPath);
        var current = await RunWslCaptureAsync(
            target.Distro,
            $"if [ -f {project}/.mkva-managed-install ]; then " +
            $"release=$(sed -n 's/^release=//p' {project}/.mkva-managed-install | head -n 1); " +
            $"revision=$(sed -n 's/^revision=//p' {project}/.mkva-managed-install | head -n 1); " +
            "printf '%s|%s' \"$release\" \"$revision\"; fi",
            cancellationToken,
            target.User);
        if (current.ExitCode != 0) return;

        var parts = current.Output.Trim().Split('|', 2);
        var installedRef = parts.ElementAtOrDefault(0) ?? string.Empty;
        var installedRevision = parts.ElementAtOrDefault(1) ?? string.Empty;
        if (installedRef.Length == 0) return;

        var healthy = await ManagedRuntimeHealthyAsync(target, cancellationToken);
        if (installedRef.Equals(ReleaseRef, StringComparison.Ordinal) &&
            installedRevision.Equals(ReleaseRevision, StringComparison.Ordinal) &&
            healthy) return;

        if (installedRef.Equals(ReleaseRef, StringComparison.Ordinal) &&
            installedRevision.Equals(ReleaseRevision, StringComparison.Ordinal))
            Message?.Invoke("Reparando os componentes da instalação gerenciada...");
        else
            Message?.Invoke($"Atualizando a instalação gerenciada de {installedRef} para {ReleaseRef}...");

        await StopExistingWebtoolAsync(target, cancellationToken);
        await RunBootstrapAsync(target.Distro, target.ProjectPath, target.User, cancellationToken);
    }

    private async Task<bool> ManagedRuntimeHealthyAsync(WslTarget target, CancellationToken cancellationToken)
    {
        var project = ShellQuote(target.ProjectPath);
        var command =
            $"PROJECT={project}; MARKER=\"$PROJECT/.mkva-managed-install\"; " +
            "BASE=$(sed -n 's/^conda_base=//p' \"$MARKER\" 2>/dev/null | head -n 1); " +
            "if [ -z \"$BASE\" ]; then for b in \"$HOME/miniforge3\" \"$HOME/miniconda3\" \"$HOME/anaconda3\" \"$HOME/mambaforge\"; do " +
            "if [ -x \"$b/envs/mkva-webtool/bin/npm\" ]; then BASE=\"$b\"; break; fi; done; fi; " +
            "test -n \"$BASE\" && test -x \"$BASE/envs/mkva-webtool/bin/node\" && " +
            "test -x \"$BASE/envs/mkva-webtool/bin/npm\" && test -x \"$BASE/envs/nextflow/bin/nextflow\" && " +
            "test -x \"$BASE/envs/nextflow/bin/java\" && test -d \"$PROJECT/webtool/dist\"";
        var result = await RunWslCaptureAsync(
            target.Distro, command, cancellationToken, target.User);
        return result.ExitCode == 0;
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

        var selectedUser = installedDistroNow
            ? "mkva"
            : (await RunWslCaptureAsync(distro, "id -un", cancellationToken)).Output.Trim();
        if (string.IsNullOrWhiteSpace(selectedUser))
            throw new InvalidOperationException("Não foi possível identificar o usuário padrão da distribuição WSL.");

        Message?.Invoke("Baixando e configurando a WebTool. Isso pode levar vários minutos...");
        var targetPath = await RunBootstrapAsync(distro, null, selectedUser, cancellationToken);

        var target = new WslTarget(distro, targetPath, selectedUser);
        SaveConfiguration(target);
        Target = target;
        return target;
    }

    private async Task<string> RunBootstrapAsync(
        string distro,
        string? installDir,
        string? user,
        CancellationToken cancellationToken)
    {
        var bootstrapPath = Path.Combine(AppContext.BaseDirectory, "bootstrap-wsl.sh");
        if (!File.Exists(bootstrapPath))
            throw new InvalidOperationException("O instalador está incompleto: bootstrap-wsl.sh não foi encontrado.");

        var script = await File.ReadAllTextAsync(bootstrapPath, cancellationToken);
        var encoded = Convert.ToBase64String(Encoding.UTF8.GetBytes(script));
        var installExport = string.IsNullOrWhiteSpace(installDir)
            ? string.Empty
            : $" export MKVA_INSTALL_DIR={ShellQuote(installDir)};";
        var shellCommand = $"export MKVA_RELEASE_REF={ShellQuote(ReleaseRef)}; " +
                           $"export MKVA_RELEASE_REVISION={ShellQuote(ReleaseRevision)};{installExport} " +
                           $"printf '%s' '{encoded}' | base64 -d | bash";
        var result = await RunWslStreamingAsync(distro, shellCommand, cancellationToken, user);
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
        return targetPath;
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
        Message?.Invoke("Preparando a interface local...");
        await StopConflictingWebtoolsAsync(target, cancellationToken);
        Message?.Invoke($"Iniciando {target.Distro} silenciosamente...");
        StartWsl(target);

        var deadline = DateTime.UtcNow.AddMinutes(2);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (await IsReadyAsync(cancellationToken))
            {
                Message?.Invoke("Webtool pronta.");
                return true;
            }

            if (_wslProcess?.HasExited == true)
            {
                await Task.Delay(250, cancellationToken);
                if (await IsReadyAsync(cancellationToken))
                {
                    Message?.Invoke("Webtool pronta.");
                    return true;
                }
                var detail = LastRecentError();
                throw new InvalidOperationException(
                    "O serviço encerrou antes de iniciar" +
                    (string.IsNullOrWhiteSpace(detail) ? "." : $": {detail}") +
                    $" Consulte o log em {LogPath}");
            }

            await Task.Delay(1500, cancellationToken);
        }

        throw new TimeoutException($"A webtool não ficou pronta em dois minutos. Consulte {LogPath}");
    }

    public static async Task<bool> IsReadyAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await Http.GetAsync("http://127.0.0.1:8787/api/health", cancellationToken);
            if (!response.IsSuccessStatusCode) return false;
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
            if (!document.RootElement.TryGetProperty("service_protocol", out var serviceProtocol) ||
                serviceProtocol.GetInt32() != 2)
                return false;
            if (!document.RootElement.TryGetProperty("picker_bridge", out var bridge) || !bridge.GetBoolean())
                return false;
            if (!document.RootElement.TryGetProperty("picker_protocol", out var protocol) ||
                protocol.GetInt32() != 1)
                return false;
            return await ReturnsSuccessAsync("http://127.0.0.1:3000/", cancellationToken);
        }
        catch
        {
            return false;
        }
    }

    public void OpenApplication()
    {
        if (ApplicationWindow.TryActivateExisting()) return;

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
        var pickerExport = string.IsNullOrWhiteSpace(PickerDirectory)
            ? string.Empty
            : $"export MKVA_PICKER_DIR=$(wslpath -a -u {ShellQuote(PickerDirectory)}); ";
        var command = $"set -e; PROJECT={project}; {pickerExport}cd \"$PROJECT/webtool\"; " +
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
        if (!string.IsNullOrWhiteSpace(target.User))
        {
            info.ArgumentList.Add("-u");
            info.ArgumentList.Add(target.User);
        }
        info.ArgumentList.Add("--");
        info.ArgumentList.Add("bash");
        info.ArgumentList.Add("-lc");
        info.ArgumentList.Add(WrapShellCommand(command));

        ClearRecentOutput();
        var process = new Process { StartInfo = info, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) AppendLog(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is not null) AppendLog("ERRO: " + e.Data); };
        process.Exited += (_, _) => AppendLog($"Processo WSL encerrado com código {process.ExitCode}.");
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        _wslProcess = process;
        AppendLog($"Iniciado em {DateTime.Now:yyyy-MM-dd HH:mm:ss}: {target.Distro} {target.ProjectPath} usuário={target.User}");
    }

    private async Task StopConflictingWebtoolsAsync(WslTarget target, CancellationToken cancellationToken)
    {
        var recognizedMkva = await IsMkvaServiceAsync(cancellationToken);
        if (recognizedMkva)
            AppendLog("Instancia MK-Viral-Assembly anterior identificada; iniciando substituicao controlada.");

        await StopExistingWebtoolAsync(target, cancellationToken);

        List<string> distros;
        try { distros = await ListDistributionsAsync(cancellationToken); }
        catch { distros = new List<string>(); }
        const string command =
            "for helper in /home/*/MK-Viral-Assembly/webtool/stop-local.py /root/MK-Viral-Assembly/webtool/stop-local.py; do " +
            "if [ -f \"$helper\" ]; then python3 \"$helper\"; fi; done";
        foreach (var distro in distros.Where(value =>
                     !value.Equals(target.Distro, StringComparison.OrdinalIgnoreCase)))
        {
            var result = await RunWslCaptureAsync(distro, command, cancellationToken, "root");
            if (!string.IsNullOrWhiteSpace(result.Output))
                AppendLog($"{distro}: {result.Output.Trim()}");
        }

        for (var attempt = 0; attempt < 40; attempt++)
        {
            var apiActive = await ReturnsSuccessAsync("http://127.0.0.1:8787/api/health", cancellationToken);
            var uiActive = await ReturnsSuccessAsync("http://127.0.0.1:3000/", cancellationToken);
            if (!apiActive && !uiActive) return;
            await Task.Delay(250, cancellationToken);
        }

        throw new InvalidOperationException(recognizedMkva
            ? "Nao foi possivel substituir a instancia anterior do MK-Viral-Assembly nas portas 3000/8787. " +
              $"Consulte o log em {LogPath}."
            : "Outro programa esta usando as portas 3000 ou 8787. " +
              "Feche esse programa e tente novamente.");
    }

    private async Task StopExistingWebtoolAsync(WslTarget target, CancellationToken cancellationToken)
    {
        var project = ShellQuote(target.ProjectPath);
        var command = $"PROJECT={project}; " +
                      "if [ -f \"$PROJECT/webtool/stop-local.py\" ]; then " +
                      "python3 \"$PROJECT/webtool/stop-local.py\"; " +
                      "else for proc in /proc/[0-9]*; do " +
                      "cwd=$(readlink \"$proc/cwd\" 2>/dev/null || true); " +
                      "case \"$cwd\" in \"$PROJECT/webtool\"|\"$PROJECT/webtool/\"*) " +
                      "kill -TERM \"${proc##*/}\" 2>/dev/null || true ;; esac; done; fi";
        var result = await RunWslCaptureAsync(target.Distro, command, cancellationToken, "root");
        if (!string.IsNullOrWhiteSpace(result.Output)) AppendLog(result.Output.Trim());
        if (result.ExitCode != 0)
            AppendLog("Falha ao encerrar servico antigo: " + result.Output.Trim());
    }

    private static async Task<bool> IsMkvaServiceAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await Http.GetAsync("http://127.0.0.1:8787/api/health", cancellationToken);
            if (!response.IsSuccessStatusCode) return false;
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
            return document.RootElement.TryGetProperty("ok", out var ok) && ok.GetBoolean() &&
                   document.RootElement.TryGetProperty("project", out var project) &&
                   (project.GetString() ?? string.Empty).Contains("MK-Viral-Assembly", StringComparison.Ordinal);
        }
        catch
        {
            return false;
        }
    }

    private async Task<bool> ProbeTargetAsync(WslTarget target, CancellationToken cancellationToken)
    {
        var project = ShellQuote(target.ProjectPath);
        var result = await RunWslCaptureAsync(
            target.Distro,
            $"test -x {project}/webtool/start-local.sh && test -f {project}/main.nf",
            cancellationToken,
            target.User);
        return result.ExitCode == 0;
    }

    private async Task<WslTarget> ResolveTargetUserAsync(WslTarget target, CancellationToken cancellationToken)
    {
        if (!string.IsNullOrWhiteSpace(target.User)) return target;
        var project = ShellQuote(target.ProjectPath);
        var result = await RunWslCaptureAsync(
            target.Distro,
            $"stat -c %U {project}",
            cancellationToken);
        var user = result.Output.Trim().Split('\n', StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? string.Empty;
        return target with { User = user };
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
            ? new WslTarget(distro, project, values.GetValueOrDefault("user", string.Empty))
            : null;
    }

    private void SaveConfiguration(WslTarget target)
    {
        Directory.CreateDirectory(_dataDir);
        File.WriteAllLines(Path.Combine(_dataDir, "launcher.conf"), new[]
        {
            $"distro={target.Distro}",
            $"project={target.ProjectPath}",
            $"user={target.User}"
        });
    }

    private void ClearRecentOutput()
    {
        lock (_logLock) _recentOutput.Clear();
    }

    private string LastRecentError()
    {
        lock (_logLock)
        {
            return _recentOutput
                .Reverse()
                .FirstOrDefault(line =>
                    !line.StartsWith("Processo WSL encerrado", StringComparison.OrdinalIgnoreCase) &&
                    !string.IsNullOrWhiteSpace(line)) ?? string.Empty;
        }
    }

    private void AppendLog(string message)
    {
        lock (_logLock)
        {
            foreach (var line in message.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                _recentOutput.Enqueue(line.Trim());
                while (_recentOutput.Count > 30) _recentOutput.Dequeue();
            }
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


internal sealed record PickerRequest(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("mode")] string Mode,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("initial")] string Initial,
    [property: JsonPropertyName("filter")] string Filter,
    [property: JsonPropertyName("default_name")] string DefaultName);

internal sealed record PickerResponse(
    [property: JsonPropertyName("cancelled")] bool Cancelled,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("error")] string Error = "");

internal sealed record PickerDialogOutcome(
    DialogResult Result,
    string Path,
    bool TopmostObserved,
    bool ForegroundObserved);

internal sealed class NativePickerBridge : IDisposable
{
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 100 };
    private readonly string _heartbeatPath;
    private DateTime _lastHeartbeat = DateTime.MinValue;
    private bool _processing;

    public string DirectoryPath { get; }

    public NativePickerBridge()
    {
        DirectoryPath = System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "MK-Viral-Assembly", "picker");
        Directory.CreateDirectory(DirectoryPath);
        _heartbeatPath = System.IO.Path.Combine(DirectoryPath, "heartbeat");
        CleanupStaleFiles();
        UpdateHeartbeat(force: true);
        _timer.Tick += ProcessRequests;
        _timer.Start();
    }

    private void CleanupStaleFiles()
    {
        foreach (var pattern in new[] { "request-*.json", "response-*.json", ".request-*.tmp", ".response-*.tmp" })
        {
            foreach (var file in Directory.EnumerateFiles(DirectoryPath, pattern))
            {
                try { File.Delete(file); } catch (IOException) { }
            }
        }
    }

    private void UpdateHeartbeat(bool force = false)
    {
        var current = DateTime.UtcNow;
        if (!force && current - _lastHeartbeat < TimeSpan.FromSeconds(1)) return;
        try
        {
            if (File.Exists(_heartbeatPath))
                File.SetLastWriteTimeUtc(_heartbeatPath, current);
            else
                File.WriteAllText(_heartbeatPath, current.ToString("O"));
            _lastHeartbeat = current;
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    private void ProcessRequests(object? sender, EventArgs e)
    {
        UpdateHeartbeat();
        if (_processing) return;
        var requestPath = Directory.EnumerateFiles(DirectoryPath, "request-*.json")
            .OrderBy(File.GetCreationTimeUtc)
            .FirstOrDefault();
        if (requestPath is null) return;

        _processing = true;
        try
        {
            PickerRequest? request = null;
            PickerResponse response;
            try
            {
                request = JsonSerializer.Deserialize<PickerRequest>(File.ReadAllText(requestPath));
                if (request is null || request.Id.Length != 32 || !request.Id.All(Uri.IsHexDigit))
                    throw new InvalidDataException("Pedido de seletor invalido.");
                var expectedName = $"request-{request.Id}.json";
                if (!System.IO.Path.GetFileName(requestPath).Equals(expectedName, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Identificador de seletor invalido.");
                var outcome = NativePickerDialogs.Show(request);
                response = new PickerResponse(
                    outcome.Result != DialogResult.OK || string.IsNullOrWhiteSpace(outcome.Path),
                    outcome.Result == DialogResult.OK ? outcome.Path : "");
            }
            catch (Exception ex)
            {
                var id = request?.Id;
                if (string.IsNullOrWhiteSpace(id))
                {
                    id = System.IO.Path.GetFileNameWithoutExtension(requestPath)
                        .Replace("request-", "", StringComparison.OrdinalIgnoreCase);
                }
                response = new PickerResponse(true, "", "Nao foi possivel abrir o seletor nativo do Windows: " + ex.Message);
                WriteResponse(id, response);
                return;
            }

            WriteResponse(request.Id, response);
        }
        finally
        {
            try { File.Delete(requestPath); } catch (IOException) { }
            _processing = false;
        }
    }

    private void WriteResponse(string id, PickerResponse response)
    {
        if (id.Length != 32 || !id.All(Uri.IsHexDigit)) return;
        var responsePath = System.IO.Path.Combine(DirectoryPath, $"response-{id}.json");
        var temporaryPath = System.IO.Path.Combine(DirectoryPath, $".response-{id}.tmp");
        File.WriteAllText(temporaryPath, JsonSerializer.Serialize(response));
        File.Move(temporaryPath, responsePath, true);
    }

    public void Dispose()
    {
        _timer.Stop();
        _timer.Dispose();
        try { File.Delete(_heartbeatPath); } catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}

internal static class NativePickerDialogs
{
    public static PickerDialogOutcome Show(
        PickerRequest request,
        bool diagnostic = false,
        bool diagnosticAccept = false)
    {
        using var owner = new Form
        {
            Text = "MK-Viral-Assembly",
            FormBorderStyle = FormBorderStyle.FixedToolWindow,
            ShowInTaskbar = false,
            StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000),
            Size = new Size(1, 1),
            Opacity = 0,
            TopMost = true
        };
        owner.Show();
        NativeDialogWindow.MakeTopmost(owner.Handle);

        var topmostObserved = false;
        var foregroundObserved = false;
        var started = Stopwatch.StartNew();
        using var promoter = new System.Windows.Forms.Timer { Interval = 40 };
        promoter.Tick += (_, _) =>
        {
            var dialogs = NativeDialogWindow.PromoteThreadDialogs(owner.Handle);
            topmostObserved |= dialogs.Any(NativeDialogWindow.IsTopmost);
            foregroundObserved |= dialogs.Any(handle => handle == NativeDialogWindow.GetForegroundWindow());
            if (!diagnostic && dialogs.Count > 0)
            {
                // Once the owned dialog is in front, stop forcing focus. Keeping
                // this timer active can interrupt the Open/Select button click.
                promoter.Stop();
            }
            if (diagnostic && started.ElapsedMilliseconds >= 900)
            {
                promoter.Stop();
                if (diagnosticAccept)
                    SendKeys.SendWait("{ENTER}");
                else
                    foreach (var handle in dialogs)
                        NativeDialogWindow.Close(handle);
            }
        };
        promoter.Start();

        try
        {
            return request.Mode switch
            {
                "folder" => ShowFolder(owner, request, ref topmostObserved, ref foregroundObserved),
                "file" => ShowOpen(owner, request, ref topmostObserved, ref foregroundObserved),
                "save" => ShowSave(owner, request, ref topmostObserved, ref foregroundObserved),
                _ => throw new InvalidDataException("Modo de seletor nao permitido.")
            };
        }
        finally
        {
            promoter.Stop();
            owner.Close();
        }
    }

    private static PickerDialogOutcome ShowFolder(
        Form owner, PickerRequest request, ref bool topmost, ref bool foreground)
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = request.Title,
            UseDescriptionForTitle = true,
            ShowNewFolderButton = true,
            SelectedPath = Directory.Exists(request.Initial) ? request.Initial : ""
        };
        var result = dialog.ShowDialog(owner);
        Observe(ref topmost, ref foreground);
        return new PickerDialogOutcome(result, result == DialogResult.OK ? dialog.SelectedPath : "", topmost, foreground);
    }

    private static PickerDialogOutcome ShowOpen(
        Form owner, PickerRequest request, ref bool topmost, ref bool foreground)
    {
        using var dialog = new OpenFileDialog
        {
            Title = request.Title,
            Filter = NormalizeFilter(request.Filter),
            CheckFileExists = true,
            CheckPathExists = true,
            RestoreDirectory = true
        };
        ApplyInitial(dialog, request.Initial);
        var result = dialog.ShowDialog(owner);
        Observe(ref topmost, ref foreground);
        return new PickerDialogOutcome(result, result == DialogResult.OK ? dialog.FileName : "", topmost, foreground);
    }

    private static PickerDialogOutcome ShowSave(
        Form owner, PickerRequest request, ref bool topmost, ref bool foreground)
    {
        using var dialog = new SaveFileDialog
        {
            Title = request.Title,
            Filter = NormalizeFilter(request.Filter),
            CheckPathExists = true,
            RestoreDirectory = true,
            OverwritePrompt = true,
            FileName = request.DefaultName
        };
        ApplyInitial(dialog, request.Initial);
        var result = dialog.ShowDialog(owner);
        Observe(ref topmost, ref foreground);
        return new PickerDialogOutcome(result, result == DialogResult.OK ? dialog.FileName : "", topmost, foreground);
    }

    private static void ApplyInitial(FileDialog dialog, string initial)
    {
        if (string.IsNullOrWhiteSpace(initial)) return;
        if (Directory.Exists(initial))
        {
            dialog.InitialDirectory = initial;
            return;
        }
        var parent = System.IO.Path.GetDirectoryName(initial);
        if (!string.IsNullOrWhiteSpace(parent) && Directory.Exists(parent))
        {
            dialog.InitialDirectory = parent;
            if (File.Exists(initial)) dialog.FileName = System.IO.Path.GetFileName(initial);
        }
    }

    private static string NormalizeFilter(string filter) =>
        string.IsNullOrWhiteSpace(filter) || filter.Count(ch => ch == '|') % 2 == 0
            ? "Todos os arquivos (*.*)|*.*"
            : filter;

    private static void Observe(ref bool topmost, ref bool foreground)
    {
        var dialogs = NativeDialogWindow.ThreadDialogs(IntPtr.Zero);
        topmost |= dialogs.Any(NativeDialogWindow.IsTopmost);
        foreground |= dialogs.Any(handle => handle == NativeDialogWindow.GetForegroundWindow());
    }
}

internal static class NativeDialogWindow
{
    private const int GwlExStyle = -20;
    private const long WsExTopmost = 0x00000008L;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoMove = 0x0002;
    private const uint SwpShowWindow = 0x0040;
    private const uint WmClose = 0x0010;
    private static readonly IntPtr HwndTopmost = new(-1);

    internal delegate bool EnumThreadDelegate(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumThreadWindows(uint threadId, EnumThreadDelegate callback, IntPtr lParam);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr insertAfter, int x, int y, int cx, int cy, uint flags);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);

    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern IntPtr SetFocus(IntPtr hWnd);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int index);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    public static List<IntPtr> ThreadDialogs(IntPtr owner)
    {
        var windows = new List<IntPtr>();
        EnumThreadWindows(GetCurrentThreadId(), (handle, _) =>
        {
            if (handle != owner && IsWindowVisible(handle))
                windows.Add(handle);
            return true;
        }, IntPtr.Zero);
        return windows;
    }

    public static List<IntPtr> PromoteThreadDialogs(IntPtr owner)
    {
        var dialogs = ThreadDialogs(owner);
        foreach (var handle in dialogs)
            ActivateTopmost(handle);
        return dialogs;
    }

    public static void MakeTopmost(IntPtr handle) =>
        SetWindowPos(handle, HwndTopmost, 0, 0, 0, 0, SwpNoMove | SwpNoSize | SwpShowWindow);

    public static void ActivateTopmost(IntPtr handle)
    {
        MakeTopmost(handle);
        var currentThread = GetCurrentThreadId();
        var foreground = GetForegroundWindow();
        var foregroundThread = foreground == IntPtr.Zero
            ? 0
            : GetWindowThreadProcessId(foreground, out _);
        var attached = foregroundThread != 0 && foregroundThread != currentThread &&
                       AttachThreadInput(currentThread, foregroundThread, true);
        try
        {
            BringWindowToTop(handle);
            SetForegroundWindow(handle);
            SetFocus(handle);
        }
        finally
        {
            if (attached) AttachThreadInput(currentThread, foregroundThread, false);
        }
    }

    public static bool IsTopmost(IntPtr handle) =>
        (GetWindowLongPtr(handle, GwlExStyle).ToInt64() & WsExTopmost) != 0;

    public static void Close(IntPtr handle) =>
        PostMessage(handle, WmClose, IntPtr.Zero, IntPtr.Zero);
}

internal static class NativePickerDiagnostics
{
    public static int Write(string reportPath)
    {
        var requests = new[]
        {
            new PickerRequest(new string('1', 32), "folder", "Teste de pasta", "", "", ""),
            new PickerRequest(new string('2', 32), "file", "Teste de arquivo", "", "Todos os arquivos (*.*)|*.*", ""),
            new PickerRequest(new string('3', 32), "save", "Teste de salvamento", "", "Texto (*.txt)|*.txt", "teste.txt")
        };
        var tests = new List<object>();
        var ok = true;
        foreach (var request in requests)
        {
            try
            {
                var outcome = NativePickerDialogs.Show(request, diagnostic: true);
                var passed = outcome.Result == DialogResult.Cancel && outcome.TopmostObserved;
                ok &= passed;
                tests.Add(new
                {
                    kind = request.Mode,
                    result = outcome.Result.ToString(),
                    topmost = outcome.TopmostObserved,
                    foreground = outcome.ForegroundObserved,
                    ok = passed
                });
            }
            catch (Exception ex)
            {
                ok = false;
                tests.Add(new { kind = request.Mode, result = "Error", topmost = false, foreground = false, ok = false, error = ex.Message });
            }
        }

        var fullPath = System.IO.Path.GetFullPath(reportPath);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(fullPath)!);
        File.WriteAllText(fullPath, JsonSerializer.Serialize(new { ok, tests }, new JsonSerializerOptions { WriteIndented = true }));
        return ok ? 0 : 1;
    }

    public static int WriteSelection(string reportPath, string directory)
    {
        var expected = System.IO.Path.GetFullPath(directory);
        Directory.CreateDirectory(expected);
        try
        {
            var request = new PickerRequest(
                new string('4', 32),
                "folder",
                "Teste de confirmação de pasta",
                expected,
                "",
                "");
            var outcome = NativePickerDialogs.Show(
                request,
                diagnostic: true,
                diagnosticAccept: true);
            var selected = string.IsNullOrWhiteSpace(outcome.Path)
                ? ""
                : System.IO.Path.GetFullPath(outcome.Path);
            var ok = outcome.Result == DialogResult.OK &&
                     string.Equals(selected.TrimEnd('\\'), expected.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);
            WriteSelectionReport(reportPath, new
            {
                ok,
                result = outcome.Result.ToString(),
                expected,
                selected,
                topmost = outcome.TopmostObserved,
                foreground = outcome.ForegroundObserved
            });
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            WriteSelectionReport(reportPath, new { ok = false, expected, error = ex.ToString() });
            return 1;
        }
    }

    private static void WriteSelectionReport(string reportPath, object report)
    {
        var fullPath = System.IO.Path.GetFullPath(reportPath);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(fullPath)!);
        File.WriteAllText(
            fullPath,
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    }
}

internal sealed class LauncherContext : ApplicationContext
{
    private readonly LauncherEngine _engine = new();
    private readonly LauncherForm _form;
    private readonly NativePickerBridge _pickerBridge;
    private readonly NotifyIcon _tray;
    private readonly CancellationTokenSource _cancellation = new();
    private readonly EventWaitHandle _activationSignal;
    private readonly RegisteredWaitHandle _activationRegistration;
    private bool _exiting;
    private bool _ready;

    public LauncherContext(EventWaitHandle activationSignal)
    {
        _activationSignal = activationSignal;
        _form = new LauncherForm();
        _pickerBridge = new NativePickerBridge();
        _engine.PickerDirectory = _pickerBridge.DirectoryPath;
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
        _activationRegistration = ThreadPool.RegisterWaitForSingleObject(
            _activationSignal,
            (_, _) => ActivateFromShortcut(),
            null,
            Timeout.Infinite,
            executeOnlyOnce: false);
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
            _ready = true;
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
            _ready = false;
            _form.SetError(ex.Message);
            _tray.Text = "MK-Viral-Assembly · atenção necessária";
        }
    }

    private async Task StopAsync()
    {
        await _engine.StopStartedServiceAsync();
        _ready = false;
        _form.SetStopped();
        ShowForm();
    }

    private void ActivateFromShortcut()
    {
        if (_exiting || _form.IsDisposed) return;
        try
        {
            _form.BeginInvoke(new Action(() =>
            {
                if (_exiting) return;
                if (_ready)
                {
                    _engine.OpenApplication();
                    _form.Hide();
                }
                else
                {
                    ShowForm();
                }
            }));
        }
        catch (InvalidOperationException)
        {
        }
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
        _activationRegistration.Unregister(null);
        _pickerBridge.Dispose();
        _engine.Dispose();
        _form.Close();
        ExitThread();
    }
}

internal static class ApplicationWindow
{
    private const int SwRestore = 9;

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int command);

    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    public static bool TryActivateExisting()
    {
        foreach (var processName in new[] { "msedge", "chrome" })
        {
            foreach (var process in Process.GetProcessesByName(processName))
            {
                using (process)
                {
                    try
                    {
                        var handle = process.MainWindowHandle;
                        var title = process.MainWindowTitle;
                        if (handle == IntPtr.Zero ||
                            !string.Equals(title.Trim(), "MK-Viral-Assembly Webtool", StringComparison.OrdinalIgnoreCase))
                            continue;
                        if (IsIconic(handle)) ShowWindow(handle, SwRestore);
                        BringWindowToTop(handle);
                        SetForegroundWindow(handle);
                        return true;
                    }
                    catch (InvalidOperationException)
                    {
                    }
                    catch (System.ComponentModel.Win32Exception)
                    {
                    }
                }
            }
        }
        return false;
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
        var pickerDirectory = Path.Combine(
            Path.GetTempPath(), "mkva-launcher-diagnostic-" + Guid.NewGuid().ToString("N"));
        using var heartbeatCancellation = new CancellationTokenSource();
        Task? heartbeatTask = null;
        if (startService)
        {
            Directory.CreateDirectory(pickerDirectory);
            engine.PickerDirectory = pickerDirectory;
            heartbeatTask = MaintainHeartbeatAsync(pickerDirectory, heartbeatCancellation.Token);
        }
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
        finally
        {
            heartbeatCancellation.Cancel();
            if (heartbeatTask is not null)
            {
                try { await heartbeatTask; }
                catch (OperationCanceledException) { }
            }
            try { Directory.Delete(pickerDirectory, recursive: true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    private static async Task MaintainHeartbeatAsync(string directory, CancellationToken cancellationToken)
    {
        var heartbeat = Path.Combine(directory, "heartbeat");
        while (!cancellationToken.IsCancellationRequested)
        {
            await File.WriteAllTextAsync(heartbeat, DateTime.UtcNow.ToString("O"), cancellationToken);
            await Task.Delay(500, cancellationToken);
        }
    }
}
