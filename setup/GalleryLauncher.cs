using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("CG 鉴赏安装助手")]
[assembly: AssemblyProduct("勇者小队全灭了修改器")]
[assembly: AssemblyVersion("1.4.0.0")]
[assembly: AssemblyFileVersion("1.4.0.0")]
[assembly: AssemblyInformationalVersion("1.4")]

internal static class GalleryLauncher
{
    private static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length != 2 || (args[0] != "status" && args[0] != "enable" && args[0] != "disable"))
        {
            Console.Error.WriteLine("用法：GallerySetup.exe status|enable|disable 游戏目录");
            return 1;
        }
        try
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(baseDir, "gallery", "code", "GallerySetup.py");
            string python = Path.Combine(baseDir, "gallery", "runtime", "python.exe");
            string path = Path.GetFullPath(args[1]).TrimEnd(Path.DirectorySeparatorChar);
            if (path.IndexOf('"') >= 0 || !File.Exists(script) || !File.Exists(python))
                throw new IOException("请完整解压修改器与 gallery 文件夹。");
            var start = new ProcessStartInfo(python,
                "-B -I -X utf8 \"" + script + "\" " + args[0] + " \"" + path + "\"");
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
            start.WorkingDirectory = baseDir;
            using (var child = Process.Start(start))
            {
                var stdout = child.StandardOutput.ReadToEndAsync();
                var stderr = child.StandardError.ReadToEndAsync();
                child.WaitForExit();
                Console.Write(stdout.GetAwaiter().GetResult());
                Console.Error.Write(stderr.GetAwaiter().GetResult());
                return child.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }
}
