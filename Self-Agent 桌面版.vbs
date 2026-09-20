' Self-Agent 桌面客户端启动器（双击运行，无控制台窗口）
' 用 venv 里的 pythonw 跑 app.pyw：界面窗口由 pywebview 提供，全程不弹黑框
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
pythonw = root & "\.venv\Scripts\pythonw.exe"
app = root & "\clients\desktop\app.pyw"

If Not fso.FileExists(pythonw) Then
    MsgBox "未找到虚拟环境解释器：" & pythonw & vbCrLf & "请先在仓库根目录执行 uv sync", 16, "Self-Agent"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Run """" & pythonw & """ """ & app & """", 0, False
