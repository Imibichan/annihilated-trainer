using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace Trainer
{
    public enum GalleryStatus { Enabled = 0, Disabled = 10, UpdateAvailable = 11 }

    public sealed class GalleryRecoveryRequired : IOException
    {
        public GalleryRecoveryRequired(string message) : base(message) { }
    }

    public sealed class GalleryRunner
    {
        readonly string helper;

        public GalleryRunner(string applicationFolder)
        {
            helper = Path.Combine(Path.GetFullPath(applicationFolder), "GallerySetup.exe");
        }

        int Run(string verb, string directory, bool checkingStatus)
        {
            if (!GalleryLocation.IsGameDirectory(directory))
                throw new DirectoryNotFoundException("请选择包含 Annihilated.exe 和 Annihilated_Data 的游戏目录。");
            if (!File.Exists(helper))
                throw new FileNotFoundException("缺少 GallerySetup.exe，请将其与修改器放在同一文件夹。");

            // Windows doubles the trailing backslashes of a quoted argument before its closing quote.
            string full = Path.GetFullPath(directory);
            string end = full.Substring(full.TrimEnd('\\').Length);
            var start = new ProcessStartInfo(helper, verb + " \"" + full + end + "\"")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = Path.GetDirectoryName(helper),
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardErrorEncoding = Encoding.UTF8,
                StandardOutputEncoding = Encoding.UTF8
            };
            using (var process = Process.Start(start))
            {
                var output = process.StandardOutput.ReadToEndAsync();
                var error = process.StandardError.ReadToEndAsync();
                process.WaitForExit();
                Task.WaitAll(output, error);
                int code = process.ExitCode;
                if (code == 0 || (checkingStatus && (code == 10 || code == 11))) return code;
                var explanation = error.Result.Trim();
                const string recovery = "RECOVERY_REQUIRED ";
                if (code == 1 && explanation.StartsWith(recovery, StringComparison.Ordinal))
                    throw new GalleryRecoveryRequired(explanation.Substring(recovery.Length));
                if (explanation.Length == 0) explanation = "GallerySetup.exe 返回错误码 " + code + "。";
                throw new IOException(explanation);
            }
        }

        public GalleryStatus ReadStatus(string directory) { return (GalleryStatus)Run("status", directory, true); }
        public bool IsEnabled(string directory) { return ReadStatus(directory) != GalleryStatus.Disabled; }

        public void SetEnabled(string directory, bool enabled)
        {
            var desired = enabled ? GalleryStatus.Enabled : GalleryStatus.Disabled;
            if (ReadStatus(directory) == desired) return;
            Run(enabled ? "enable" : "disable", directory, false);
            if (ReadStatus(directory) != desired) throw new IOException("操作后的安装状态核验失败，请重新读取。");
        }

        public void Recover(string directory)
        {
            Run("disable", directory, false);
            if (IsEnabled(directory)) throw new IOException("恢复后的安装状态核验失败，请重新读取。");
        }
    }
}
