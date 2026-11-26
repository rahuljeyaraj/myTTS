# A window with sample text for the hotkey test (Sandbox has no Notepad).
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form
$f.Text = 'Sample text'; $f.Width = 700; $f.Height = 300; $f.StartPosition = 'CenterScreen'
$t = New-Object Windows.Forms.TextBox
$t.Multiline = $true; $t.Dock = 'Fill'; $t.Font = New-Object Drawing.Font('Segoe UI', 14)
$t.Text = 'myTTS reads the selected text aloud. This is the second sentence. And here is a third one, so there is something to skip to.'
$f.Controls.Add($t)
$t.HideSelection = $false
$f.Add_Shown({ $f.Activate(); $t.Focus(); $t.SelectAll() })  # a multiline TextBox ignores Ctrl+A
[void]$f.ShowDialog()
