using System;
using System.IO;
using System.Text;
using System.Threading;

class LegacyMigrationFixture
{
    static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        var script = Path.Combine(Environment.CurrentDirectory, "gallery", "code", "legacy_gallery.py");
        if (args.Length != 6 || args[0] != "-X" || args[1] != "utf8" || args[2] != "-B" ||
            args[3] != script || !File.Exists(script) || !Path.IsPathRooted(args[5])) return 2;
        string folder = args[5];
        if (!File.Exists(Path.Combine(folder, "known.test")))
        {
            Console.Error.WriteLine("测试游戏版本未知");
            return 1;
        }
        string installed = Path.Combine(folder, "installed.test");
        string recovery = Path.Combine(folder, "recovery.test");
        if (args[4] == "status")
        {
            if (File.Exists(recovery))
            {
                Console.Error.WriteLine("RECOVERY_REQUIRED 测试恢复中断。");
                return 1;
            }
            return File.Exists(installed) ? 0 : 10;
        }
        if (args[4] != "disable") return 2;
        Thread.Sleep(50);
        if (!File.Exists(Path.Combine(folder, "skip-close.test")))
        {
            File.Delete(installed);
            File.Delete(recovery);
        }
        return 0;
    }
}
