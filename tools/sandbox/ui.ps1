# UI helpers for jobs in Windows Sandbox; dot-source it: . C:\in\ui.ps1
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
if (-not ('U' -as [type])) {
Add-Type @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class U {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc f, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  public static string Text(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
  public static string Class(IntPtr h) { var s = new StringBuilder(256); GetClassName(h, s, 256); return s.ToString(); }
  public static List<IntPtr> Top() { var r = new List<IntPtr>(); EnumWindows((h, l) => { if (IsWindowVisible(h)) r.Add(h); return true; }, IntPtr.Zero); return r; }
  public static List<IntPtr> Children(IntPtr p) { var r = new List<IntPtr>(); EnumChildWindows(p, (h, l) => { r.Add(h); return true; }, IntPtr.Zero); return r; }
  public static uint Pid(IntPtr h) { uint p; GetWindowThreadProcessId(h, out p); return p; }
  public static void Chord(params byte[] keys) {
    foreach (var k in keys) keybd_event(k, 0, 0, UIntPtr.Zero);
    System.Threading.Thread.Sleep(60);
    for (int i = keys.Length - 1; i >= 0; i--) keybd_event(keys[i], 0, 2, UIntPtr.Zero);
  }
}
'@
}

function Get-Windows([string]$Like = '*') {
    # Visible top-level windows whose title matches.
    [U]::Top() | ForEach-Object {
        $p = Get-Process -Id ([U]::Pid($_)) -ErrorAction SilentlyContinue
        [pscustomobject]@{ Handle = $_; Title = [U]::Text($_); Class = [U]::Class($_); Process = $p.ProcessName }
    } | Where-Object { $_.Title -like $Like -and $_.Title }
}

function Get-Controls([IntPtr]$Window) {
    [U]::Children($Window) | ForEach-Object {
        [pscustomobject]@{ Handle = $_; Class = [U]::Class($_); Text = [U]::Text($_); Visible = [U]::IsWindowVisible($_); Enabled = [U]::IsWindowEnabled($_) }
    }
}

function Show-Window([string]$Like) {
    # Prints a window's visible controls with text.
    foreach ($w in Get-Windows $Like) {
        "WINDOW [$($w.Title)] class $($w.Class) process $($w.Process)"
        Get-Controls $w.Handle | Where-Object { $_.Visible -and $_.Text } | ForEach-Object { "  $($_.Class) '$($_.Text)'$(if (-not $_.Enabled) { ' (disabled)' })" }
    }
}

function Click([string]$WindowLike, [string]$Text) {
    # Clicks the visible, enabled control whose text (without &) is $Text.
    $w = Get-Windows $WindowLike | Select-Object -First 1
    if (-not $w) { throw "no window like '$WindowLike'" }
    $c = Get-Controls $w.Handle | Where-Object { $_.Visible -and $_.Enabled -and ($_.Text -replace '&', '') -eq $Text } | Select-Object -First 1
    if (-not $c) { throw "no control '$Text' in '$($w.Title)'" }
    $null = [U]::PostMessage($c.Handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)  # BM_CLICK
    "clicked '$Text' in '$($w.Title)'"
}

function Save-Screen([string]$Name) {
    $b = [Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save("C:\out\$Name.png", [Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    "saved C:\out\$Name.png ($($b.Width)x$($b.Height))"
}
