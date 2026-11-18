using System;
using System.IO;
using System.Text;

// Offline stand-in for the fixed helper protocol. Runs only in a temporary game directory.
class GallerySetupFixture
{
    static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length != 2 || !Path.IsPathRooted(args[1])) return 1;
        string dir = args[1];
        if (!File.Exists(Path.Combine(dir, "known.test")))
        {
            Console.Error.WriteLine("测试游戏版本未知");
            return 1;
        }
        string state = Path.Combine(dir, "installed.test");
        switch (args[0])
        {
            case "status":
                if (File.Exists(Path.Combine(dir, "recovery.test")))
                {
                    Console.Error.WriteLine("RECOVERY_REQUIRED 某项操作中断。");
                    return 1;
                }
                return File.Exists(state) ? (File.Exists(Path.Combine(dir, "older.test")) ? 11 : 0) : 10;
            case "enable":
                if (!File.Exists(Path.Combine(dir, "skip-install.test")))
                {
                    File.WriteAllText(state, "");
                    File.Delete(Path.Combine(dir, "older.test"));
                }
                return 0;
            case "disable":
                File.Delete(state);
                File.Delete(Path.Combine(dir, "older.test"));
                File.Delete(Path.Combine(dir, "recovery.test"));
                return 0;
            default: return 1;
        }
    }
}
