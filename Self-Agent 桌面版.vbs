' Self-Agent 桌面客户端启动器（双击运行，无控制台窗口）
' 用 venv 里的 pythonw 跑 app.pyw：界面窗口由 pywebview 提供，全程不弹黑框
' 本脚本放在仓库根目录，所以脚本所在目录就是仓库根（只往上取一层）。
' 编码：WSH 只认 ANSI / UTF-16LE，读不了 UTF-8。.gitattributes 让本文件检出为
' UTF-16LE(BOM) + CRLF，中文提示才不乱码；仓库里存的仍是 UTF-8，diff 照常可读。
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
app = root & "\clients\desktop\app.pyw"

If Not fso.FileExists(app) Then
    MsgBox "未找到桌面客户端入口：" & app & vbCrLf & "本脚本需放在 Self-Agent 仓库根目录", 16, "Self-Agent"
    WScript.Quit 1
End If

If Not fso.FileExists(pythonw) Then
    MsgBox "未找到虚拟环境解释器：" & pythonw & vbCrLf & "请先在仓库根目录执行 uv sync", 16, "Self-Agent"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Run """" & pythonw & """ """ & app & """", 0, False
