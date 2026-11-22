using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace Trainer
{
    public enum GalleryStatus { Enabled = 0, Disabled = 10 }

    public sealed class GalleryRecoveryRequired : IOException
    {
        public GalleryRecoveryRequired(string message) : base(message) { }
    }

    public sealed class GalleryRunner
    {
        readonly string root;

        public GalleryRunner(string applicationFolder)
        {
            root = Path.GetFullPath(applicationFolder);
        }

        static string QuotePath(string directory)
        {
            string full = Path.GetFullPath(directory);
            return "\"" + full + full.Substring(full.TrimEnd('\\').Length) + "\"";
        }

        internal ProcessStartInfo ReplayStartInfo(string directory)
        {
            if (!GalleryLocation.IsGameDirectory(directory))
                throw new DirectoryNotFoundException("请选择包含 Annihilated.exe 的游戏安装目录。");
            var python = Path.Combine(root, "gallery", "runtime", "pythonw.exe");
            var script = Path.Combine(root, "gallery", "code", "replay", "launch.py");
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("未找到回放程序。请将整个 V1.6.1 压缩包解压到同一文件夹。");
            return new ProcessStartInfo(python, "-X utf8 -B " + QuotePath(script) + " --game " + QuotePath(directory))
            {
                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = root,
                RedirectStandardError = true, StandardErrorEncoding = Encoding.UTF8
            };
        }

        public void RunReplay(string directory)
        {
            using (var process = Process.Start(ReplayStartInfo(directory)))
            {
                string error = process.StandardError.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0)
                    throw new IOException(String.IsNullOrWhiteSpace(error) ? "回放启动器返回错误码 " + process.ExitCode + "。" : error.Trim());
            }
        }

        int RunMigration(string directory, bool close)
        {
            if (!GalleryLocation.IsGameDirectory(directory))
                throw new DirectoryNotFoundException("请选择包含 Annihilated.exe 和 Annihilated_Data 的游戏目录。");
            var python = Path.Combine(root, "gallery", "runtime", "python.exe");
            var script = Path.Combine(root, "gallery", "code", "legacy_gallery.py");
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("缺少旧画廊迁移组件。请完整解压 V1.6.1 发布包。");

            // Windows doubles the trailing backslashes of a quoted argument before its closing quote.
            var start = new ProcessStartInfo(python, "-X utf8 -B " + QuotePath(script) +
                (close ? " disable " : " status ") + QuotePath(directory))
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = root,
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
                if (code == 0 || (!close && code == 10)) return code;
                var explanation = error.Result.Trim();
                const string recovery = "RECOVERY_REQUIRED ";
                if (code == 1 && explanation.StartsWith(recovery, StringComparison.Ordinal))
                    throw new GalleryRecoveryRequired(explanation.Substring(recovery.Length));
                if (explanation.Length == 0) explanation = "旧画廊迁移组件返回错误码 " + code + "。";
                throw new IOException(explanation);
            }
        }

        public GalleryStatus ReadStatus(string directory) { return (GalleryStatus)RunMigration(directory, false); }

        public void CloseLegacyGallery(string directory)
        {
            RunMigration(directory, true);
            if (ReadStatus(directory) != GalleryStatus.Disabled)
                throw new IOException("旧画廊仍处于启用状态，恢复结果未通过核验。");
        }
    }
}
