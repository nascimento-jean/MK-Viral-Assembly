using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

public sealed class MkvaWindowOwner : IWin32Window
{
    public MkvaWindowOwner(IntPtr handle) { Handle = handle; }
    public IntPtr Handle { get; private set; }
}

public static class MkvaNativePicker
{
    private delegate bool EnumWindowProc(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowProc callback, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumThreadWindows(uint thread, EnumWindowProc callback, IntPtr data);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);

    private static bool IsWebtool(IntPtr window)
    {
        if (!IsWindowVisible(window)) return false;
        var title = new StringBuilder(512);
        var className = new StringBuilder(128);
        GetWindowText(window, title, title.Capacity);
        GetClassName(window, className, className.Capacity);
        return title.ToString().StartsWith("MK-Viral-Assembly Webtool", StringComparison.OrdinalIgnoreCase)
            && className.ToString().StartsWith("Chrome_WidgetWin_", StringComparison.Ordinal);
    }

    public static IWin32Window FindOwner()
    {
        IntPtr window = GetForegroundWindow();
        if (IsWebtool(window)) return new MkvaWindowOwner(window);
        // PowerShell starts asynchronously from WSL; foreground may have changed.
        window = IntPtr.Zero;
        EnumWindows(delegate(IntPtr candidate, IntPtr data) {
            if (!IsWebtool(candidate)) return true;
            window = candidate;
            return false;
        }, IntPtr.Zero);
        return window == IntPtr.Zero ? null : new MkvaWindowOwner(window);
    }

    public static DialogResult Show(CommonDialog dialog, IWin32Window owner)
    {
        uint thread = GetCurrentThreadId();
        using (var timer = new Timer())
        {
            timer.Interval = 100;
            timer.Tick += delegate {
                // Only touch the real dialog on this picker thread, never the browser.
                EnumThreadWindows(thread, delegate(IntPtr window, IntPtr data) {
                    var className = new StringBuilder(128);
                    GetClassName(window, className, className.Capacity);
                    if (!IsWindowVisible(window) || className.ToString() != "#32770") return true;
                    // HWND_TOPMOST works even when Windows denies foreground activation.
                    // The flag belongs to the dialog and disappears when it is disposed.
                    if (SetWindowPos(window, new IntPtr(-1), 0, 0, 0, 0, 0x0001 | 0x0002))
                    {
                        SetForegroundWindow(window);
                        timer.Stop();
                    }
                    return false;
                }, IntPtr.Zero);
            };
            timer.Start();
            try { return dialog.ShowDialog(owner); }
            finally { timer.Stop(); }
        }
    }
}
