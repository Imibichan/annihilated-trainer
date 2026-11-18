using System;
using System.Collections.Generic;
using System.IO;
using System.Security;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace Trainer
{
    public static class GalleryLocation
    {
        public static bool IsGameDirectory(string directory)
        {
            return !String.IsNullOrWhiteSpace(directory) && Path.IsPathRooted(directory)
                && File.Exists(Path.Combine(directory, "Annihilated.exe"))
                && Directory.Exists(Path.Combine(directory, "Annihilated_Data"));
        }

        public static string ChoicePath
        {
            get
            {
                var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return String.IsNullOrEmpty(local) ? null :
                    Path.Combine(local, "AnnihilatedTrainer", "gallery-folder.txt");
            }
        }

        public static string ReadChoice(string file)
        {
            try { return File.Exists(file) ? File.ReadAllText(file).Trim() : null; }
            catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
        }

        public static void SaveChoice(string file, string game)
        {
            if (!IsGameDirectory(game)) throw new DirectoryNotFoundException("请选择包含 Annihilated.exe 的游戏目录。");
            if (file == null) throw new IOException("无法取得当前用户的设置目录。");
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            string temp = file + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temp, Path.GetFullPath(game), new UTF8Encoding(false));
                if (File.Exists(file)) File.Replace(temp, file, null);
                else File.Move(temp, file);
            }
            finally { if (File.Exists(temp)) File.Delete(temp); }
        }

        public static IEnumerable<string> SteamRoots()
        {
            var roots = new List<string>();
            foreach (string key in new[] { @"HKEY_CURRENT_USER\Software\Valve\Steam",
                @"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam", @"HKEY_LOCAL_MACHINE\SOFTWARE\Valve\Steam" })
            {
                try
                {
                    var value = Registry.GetValue(key, key.StartsWith("HKEY_CURRENT_USER") ? "SteamPath" : "InstallPath", null) as string;
                    if (!String.IsNullOrWhiteSpace(value)) roots.Add(value);
                }
                catch (SecurityException) { }
                catch (UnauthorizedAccessException) { }
                catch (IOException) { }
            }
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            if (!String.IsNullOrEmpty(programFiles)) roots.Add(Path.Combine(programFiles, "Steam"));
            return roots;
        }

        static string ReadSteamFile(string path)
        {
            try { return File.Exists(path) ? File.ReadAllText(path) : ""; }
            catch (IOException) { return ""; }
            catch (UnauthorizedAccessException) { return ""; }
        }

        // Current library entries use "path". Old Steam clients used the numbered key itself.
        static readonly Regex LibraryPath = new Regex(@"^[ \t]*""(?:path|[0-9]+)""[ \t]+""([^""\r\n]+)""",
            RegexOptions.Multiline | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        static readonly Regex InstallDir = new Regex(@"^[ \t]*""installdir""[ \t]+""([^""\r\n]+)""",
            RegexOptions.Multiline | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        static bool ValidAbsolutePath(string value)
        {
            return !String.IsNullOrWhiteSpace(value) && value.IndexOfAny(Path.GetInvalidPathChars()) < 0
                && Path.IsPathRooted(value);
        }

        public static string Find(string preferred, IEnumerable<string> steamRoots)
        {
            if (ValidAbsolutePath(preferred) && IsGameDirectory(preferred)) return Path.GetFullPath(preferred);
            var libraries = new List<string>();
            foreach (var root in steamRoots)
            {
                if (!ValidAbsolutePath(root)) continue;
                libraries.Add(root);
                string vdf = ReadSteamFile(Path.Combine(root, "steamapps", "libraryfolders.vdf"));
                foreach (Match match in LibraryPath.Matches(vdf))
                {
                    var path = match.Groups[1].Value.Replace(@"\\", @"\");
                    if (ValidAbsolutePath(path)) libraries.Add(path);
                }
            }
            var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string library in libraries)
            {
                if (!visited.Add(library)) continue;
                string apps = Path.Combine(library, "steamapps");
                var match = InstallDir.Match(ReadSteamFile(Path.Combine(apps, "appmanifest_2638080.acf")));
                string name = match.Success ? match.Groups[1].Value : "Annihilated";
                if (name == "." || name == ".." || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0) continue;
                string game = Path.Combine(apps, "common", name);
                if (IsGameDirectory(game)) return Path.GetFullPath(game);
            }
            return null;
        }
    }
}
