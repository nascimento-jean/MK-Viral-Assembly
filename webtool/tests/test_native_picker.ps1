# Run with Windows PowerShell -STA. Opens and cancels three temporary test dialogs.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
Add-Type -ReferencedAssemblies System.Windows.Forms -Path (Join-Path $PSScriptRoot '../native_picker.cs')
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
public static class PickerProbe {
    private delegate bool Callback(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] private static extern bool EnumThreadWindows(uint thread, Callback callback, IntPtr p);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] private static extern int GetWindowLong(IntPtr h, int n);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    public static bool SawTopmost, SawForeground;
    public static Timer Start() {
        SawTopmost = false; SawForeground = false;
        uint thread = GetCurrentThreadId();
        Timer timer = new Timer(); timer.Interval = 1500;
        timer.Tick += delegate {
            EnumThreadWindows(thread, delegate(IntPtr h, IntPtr p) {
                var name = new StringBuilder(128); GetClassName(h,name,128);
                if (!IsWindowVisible(h) || name.ToString() != "#32770") return true;
                SawTopmost = (GetWindowLong(h,-20) & 8) != 0;
                SawForeground = GetForegroundWindow() == h;
                PostMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero);
                timer.Stop(); return false;
            }, IntPtr.Zero);
        };
        timer.Start(); return timer;
    }
}
"@
foreach ($kind in @('FolderBrowserDialog', 'OpenFileDialog', 'SaveFileDialog')) {
    $dialog = New-Object "System.Windows.Forms.$kind"
    $probe = [PickerProbe]::Start()
    try {
        $result = [MkvaNativePicker]::Show($dialog, $null)
        if (-not [PickerProbe]::SawTopmost) { throw "$kind did not appear on top" }
        if ($result -ne [System.Windows.Forms.DialogResult]::Cancel) { throw "$kind did not cancel" }
        Write-Output "$kind : topmost=$([PickerProbe]::SawTopmost), foreground=$([PickerProbe]::SawForeground), result=$result"
    } finally { $probe.Stop(); $probe.Dispose(); $dialog.Dispose() }
}
