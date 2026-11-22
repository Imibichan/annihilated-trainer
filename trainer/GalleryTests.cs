using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Reflection;
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

    static void ClickWithoutShowingWindow(Button action)
    {
        if (!action.Enabled) throw new Exception("Attempt to click disabled test control");
        typeof(Button).GetMethod("OnClick", BindingFlags.NonPublic | BindingFlags.Instance)
            .Invoke(action, new object[] { EventArgs.Empty });
    }

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
        using (var panel = new GalleryPanel(false, runner))
        {
            var field = (TextBox)panel.Controls.Find("galleryDirectory", true)[0];
            var state = (Label)panel.Controls.Find("galleryState", true)[0];
            var close = (Button)panel.Controls.Find("closeLegacyGallery", true)[0];
            var replay = (Button)panel.Controls.Find("storyReplay", true)[0];
            var choose = (Button)panel.Controls.Find("galleryChoose", true)[0];
            field.Text = game;
            var refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            refresh.GetAwaiter().GetResult();
            Check(!close.Enabled && state.Text.Contains("已关闭") && replay.Enabled, "clean install has replay and grey migration action");
            Touch(Path.Combine(game, "installed.test"));
            refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(close.Enabled && close.Text == "关闭旧画廊" && state.Text.Contains("已启用"), "installed gallery has only close action");
            ClickWithoutShowingWindow(close);
            Check(panel.IsApplying && !close.Enabled && !replay.Enabled && !choose.Enabled, "close serializes mutations and locks directory");
            var duplicate = panel.RefreshState();
            Check(duplicate.IsCompleted && panel.IsApplying, "parallel refresh cannot reopen controls during close");
            WaitFor(() => !panel.IsApplying);
            Check(!close.Enabled && replay.Enabled && state.Text.Contains("已关闭") && !File.Exists(Path.Combine(game, "installed.test")),
                "successful close reads back original state and leaves migration disabled");
            Touch(Path.Combine(game, "recovery.test"));
            refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(close.Enabled && close.Text == "关闭旧画廊" && state.Text.Contains("需要恢复"), "same close action can finish an interrupted restore");
            Check(File.Exists(Path.Combine(game, "recovery.test")), "inspecting an interrupted transaction is read-only");
            ClickWithoutShowingWindow(close);
            WaitFor(() => !panel.IsApplying);
            Check(state.Text.Contains("已关闭") && !File.Exists(Path.Combine(game, "recovery.test")),
                "recovery button finishes restoration and reads back actual status");
            File.Delete(Path.Combine(game, "known.test"));
            refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(!close.Enabled && replay.Enabled && state.Text.Contains("待确认"), "unknown legacy state leaves replay independent");
        }
        Touch(Path.Combine(game, "known.test"));
        Touch(Path.Combine(game, "installed.test"));
        using (var panel = new GalleryPanel(true, runner))
        {
            ((TextBox)panel.Controls.Find("galleryDirectory", true)[0]).Text = game;
            var refresh = panel.RefreshState();
            WaitFor(() => refresh.IsCompleted);
            Check(!panel.Controls.Find("closeLegacyGallery", true)[0].Enabled, "read-only mode keeps migration disabled even if installed");
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
        string replayCopy = Directory.CreateDirectory(Path.Combine(temp, "V1.5 旧副本")).FullName;
        Touch(Path.Combine(replayCopy, "Annihilated.exe"));
        Directory.CreateDirectory(Path.Combine(replayCopy, "Annihilated_Data"));
        Touch(Path.Combine(replayCopy, ".orien-replay-copy.json"));
        Check(!GalleryLocation.IsGameDirectory(replayCopy), "replay copy cannot be selected as the source game");
        Check(GalleryLocation.Find(replayCopy, roots) == game, "old saved selection falls back to the official installation");
        Check(GalleryLocation.Find(null, roots) == game, "detect custom install in second Steam library");
        Check(GalleryLocation.Find(game, new string[0]) == game, "remembered install works outside Steam");
        Check(GalleryLocation.Find(steam, roots) == game, "stale choice falls back to Steam");
        GalleryLocation.SaveChoice(settings, game);
        Check(GalleryLocation.ReadChoice(settings) == game, "manual choice survives a fresh load");
        GalleryLocation.SaveChoice(settings, game);
        Check(GalleryLocation.ReadChoice(settings) == game, "choice can be saved again");
        Check(GalleryLocation.Find(null, new string[0]) == null, "missing game is not a selection");
        Fails(() => helper.ReadStatus(steam), "Annihilated.exe");
        Fails(() => helper.ReadStatus(game), "测试游戏版本未知");

        Touch(Path.Combine(game, "known.test"));
        Check(helper.ReadStatus(game) == GalleryStatus.Disabled, "default state is disabled");
        Touch(Path.Combine(game, "installed.test"));
        Check(new GalleryRunner(temp).ReadStatus(game) == GalleryStatus.Enabled, "a fresh client observes existing old gallery");
        helper.CloseLegacyGallery(game + Path.DirectorySeparatorChar);
        helper.CloseLegacyGallery(game);
        Check(!File.Exists(Path.Combine(game, "installed.test")), "repeat disable leaves no installation");
        Touch(Path.Combine(game, "installed.test"));
        Touch(Path.Combine(game, "skip-close.test"));
        Fails(() => helper.CloseLegacyGallery(game), "核验");
        Check(helper.ReadStatus(game) == GalleryStatus.Enabled, "a lying close result cannot mark the old gallery disabled");
        Fails(() => new GalleryRunner(game).ReadStatus(game), "缺少旧画廊迁移组件");
        File.Delete(Path.Combine(game, "skip-close.test"));
        helper.CloseLegacyGallery(game);
        var previous = SynchronizationContext.Current;
        using (var context = new WindowsFormsSynchronizationContext())
        {
            SynchronizationContext.SetSynchronizationContext(context);
            try { TestPanel(game, helper); }
            finally { SynchronizationContext.SetSynchronizationContext(previous); }
        }
        Console.WriteLine("PASS " + passed + " replay location and close-only migration assertions");
    }
}
