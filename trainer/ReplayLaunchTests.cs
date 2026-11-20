using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using Trainer;

class ReplayLaunchTests
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CommandLineToArgvW(string command, out int argc);
    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr pointer);

    static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }

    static void Main()
    {
        string temp = Path.Combine(Path.GetTempPath(), "OrienReplay-" + Guid.NewGuid().ToString("N"));
        string game = Path.Combine(temp, "游戏 & (copy)");
        string python = Path.Combine(temp, "gallery", "runtime", "pythonw.exe");
        string script = Path.Combine(temp, "gallery", "code", "replay", "launch.py");
        Directory.CreateDirectory(Path.Combine(game, "Annihilated_Data"));
        try
        {
            File.WriteAllBytes(Path.Combine(game, "Annihilated.exe"), new byte[0]);
            var runner = new GalleryRunner(temp);
            bool rejected = false;
            try { runner.ReplayStartInfo(game); } catch (FileNotFoundException) { rejected = true; }
            Check(rejected, "reject incomplete package");
            foreach (string file in new[] { python, script })
            {
                Directory.CreateDirectory(Path.GetDirectoryName(file));
                File.WriteAllBytes(file, new byte[0]);
            }
            string trailing = game + Path.DirectorySeparatorChar;
            ProcessStartInfo start = runner.ReplayStartInfo(trailing);
            Check(start.FileName == python && start.WorkingDirectory == temp && !start.UseShellExecute, "local runtime");
            int count;
            IntPtr args = CommandLineToArgvW("pythonw.exe " + start.Arguments, out count);
            try
            {
                string[] expected = { "pythonw.exe", "-X", "utf8", "-B", script, "--game", trailing };
                Check(count == expected.Length, "argument count");
                for (int i = 0; i < count; i++)
                    Check(Marshal.PtrToStringUni(Marshal.ReadIntPtr(args, i * IntPtr.Size)) == expected[i], "argument " + i);
            }
            finally { LocalFree(args); }
            Console.WriteLine("PASS replay arguments, Unicode, trailing slash, local runtime and missing-file handling");
        }
        finally { Directory.Delete(temp, true); }
    }
}
