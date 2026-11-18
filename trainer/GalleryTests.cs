using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Trainer;

public static class GalleryTests
{
    static int passed;

    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
        passed++;
    }

    static void Fails(Action action, string text)
    {
        try { action(); }
        catch (Exception error)
        {
            Check(error.Message.Contains(text), "expected '" + text + "', got '" + error.Message + "'");
            return;
        }
        throw new Exception("Expected an error containing '" + text + "'");
    }

    static void Touch(string path) { File.WriteAllText(path, "", Encoding.UTF8); }

    static void WaitFor(Func<bool> complete)
    {
        var until = DateTime.UtcNow.AddSeconds(15);
        while (!complete() && DateTime.UtcNow < until)
        {
            Application.DoEvents();
            Thread.Sleep(10);
        }
        if (!complete()) throw new Exception("Gallery UI did not finish its operation in time");
    }

    static void TestPanel(string game, GalleryRunner runner)
    {
        using (var form = new Form { ShowInTaskbar = false, Opacity = 0 })
        using (var panel = new GalleryPanel(false, runner))
        {
            form.Controls.Add(panel);
            form.Show();
            var field = (TextBox)panel.Controls.Find("galleryDirectory", true)[0];
            var state = (Label)panel.Controls.Find("galleryState", true)[0];
            var toggle = (Button)panel.Controls.Find("galleryToggle", true)[0];
            field.Text = game;
            var refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            refresh.GetAwaiter().GetResult();
            Check(toggle.Enabled && state.Text.Contains("已关闭"), "offline UI can enable a verified installation");
            toggle.PerformClick();
            WaitFor(() => !panel.IsApplying);
            bool stored = runner.IsEnabled(game);
            Check(toggle.Enabled && state.Text.Contains("已启用") && stored,
                "actual enable button updates disk and label: state=" + state.Text + ", stored=" + stored +
                ", can select=" + toggle.CanSelect + ", visible=" + toggle.Visible);
            Touch(Path.Combine(game, "older.test"));
            refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            var updates = panel.Controls.Find("galleryUpdate", true);
            Check(updates.Length == 1, "existing gallery offers a distinct update action");
            var update = (Button)updates[0];
            Check(update.Visible && update.Enabled && toggle.Enabled && toggle.Text.Contains("关闭"), "old gallery can be updated or disabled");
            update.PerformClick();
            WaitFor(() => !panel.IsApplying);
            Check(!File.Exists(Path.Combine(game, "older.test")) && runner.IsEnabled(game) && !update.Visible,
                "update action installs new version and removes the stale update action");
            toggle.PerformClick();
            WaitFor(() => !panel.IsApplying);
            stored = runner.IsEnabled(game);
            Check(toggle.Enabled && state.Text.Contains("已关闭") && !stored,
                "actual disable button updates disk and label: state=" + state.Text + ", stored=" + stored +
                ", can select=" + toggle.CanSelect + ", visible=" + toggle.Visible);
            Touch(Path.Combine(game, "recovery.test"));
            refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(toggle.Enabled && toggle.Text.Contains("恢复"), "verified interruption offers an explicit recovery action");
            Check(File.Exists(Path.Combine(game, "recovery.test")), "inspecting an interrupted transaction is read-only");
            toggle.PerformClick();
            WaitFor(() => !panel.IsApplying);
            Check(state.Text.Contains("已关闭") && !File.Exists(Path.Combine(game, "recovery.test")),
                "recovery button finishes restoration and reads back actual status");
            File.Delete(Path.Combine(game, "known.test"));
            refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(!toggle.Enabled && state.Text.Contains("待确认"), "unsupported version clears an earlier verified state");
        }
        Touch(Path.Combine(game, "known.test"));
        using (var form = new Form { ShowInTaskbar = false, Opacity = 0 })
        using (var panel = new GalleryPanel(true, runner))
        {
            form.Controls.Add(panel);
            form.Show();
            ((TextBox)panel.Controls.Find("galleryDirectory", true)[0]).Text = game;
            var refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(!panel.Controls.Find("galleryToggle", true)[0].Enabled, "read-only mode keeps gallery operations disabled");
        }
    }

    public static void Run(string temp)
    {
        var helper = new GalleryRunner(temp);
        string steam = Directory.CreateDirectory(Path.Combine(temp, "Steam", "steamapps")).FullName;
        string library = Path.Combine(temp, "Steam Library 二");
        string steamApps = Directory.CreateDirectory(Path.Combine(library, "steamapps")).FullName;
        string game = Directory.CreateDirectory(Path.Combine(steamApps, "common", "custom 安装")).FullName;
        string settings = Path.Combine(temp, "preferences", "gallery-folder.txt");

        File.WriteAllText(Path.Combine(steam, "libraryfolders.vdf"),
            "\"libraryfolders\"\n{\n  \"1\"\n  {\n    \"path\"  \"" + library.Replace("\\", "\\\\") + "\"\n  }\n}");
        File.WriteAllText(Path.Combine(steamApps, "appmanifest_2638080.acf"),
            "\"AppState\"\n{\n  \"installdir\" \"custom 安装\"\n}");
        Touch(Path.Combine(game, "Annihilated.exe"));
        Directory.CreateDirectory(Path.Combine(game, "Annihilated_Data"));
        var roots = new[] { Path.GetDirectoryName(steam) };
        Check(GalleryLocation.Find(null, roots) == game, "detect custom install in second Steam library");
        Check(GalleryLocation.Find(game, new string[0]) == game, "remembered install works outside Steam");
        Check(GalleryLocation.Find(steam, roots) == game, "stale choice falls back to Steam");
        GalleryLocation.SaveChoice(settings, game);
        Check(GalleryLocation.ReadChoice(settings) == game, "manual choice survives a fresh load");
        GalleryLocation.SaveChoice(settings, game);
        Check(GalleryLocation.ReadChoice(settings) == game, "choice can be saved again");
        Check(GalleryLocation.Find(null, new string[0]) == null, "missing game is not a selection");
        Fails(() => helper.IsEnabled(steam), "Annihilated.exe");
        Fails(() => helper.IsEnabled(game), "测试游戏版本未知");

        Touch(Path.Combine(game, "known.test"));
        Check(!helper.IsEnabled(game), "default state is disabled");
        helper.SetEnabled(game, true);
        helper.SetEnabled(game, true);
        Check(File.Exists(Path.Combine(game, "installed.test")), "enable survives a repeat call");
        Check(new GalleryRunner(temp).IsEnabled(game), "a fresh client observes installed state");
        helper.SetEnabled(game + Path.DirectorySeparatorChar, false);
        helper.SetEnabled(game, false);
        Check(!File.Exists(Path.Combine(game, "installed.test")), "repeat disable leaves no installation");
        Touch(Path.Combine(game, "skip-install.test"));
        Fails(() => helper.SetEnabled(game, true), "核验");
        Check(!helper.IsEnabled(game), "a lying write result does not enable the gallery");
        Fails(() => new GalleryRunner(game).IsEnabled(game), "GallerySetup.exe");
        File.Delete(Path.Combine(game, "skip-install.test"));
        var previous = SynchronizationContext.Current;
        using (var context = new WindowsFormsSynchronizationContext())
        {
            SynchronizationContext.SetSynchronizationContext(context);
            try { TestPanel(game, helper); }
            finally { SynchronizationContext.SetSynchronizationContext(previous); }
        }
        Console.WriteLine("PASS " + passed + " gallery location and setup protocol assertions");
    }
}
