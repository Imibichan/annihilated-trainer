using System;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Trainer;

public sealed class GalleryPanel : UserControl
{
    readonly bool readOnly;
    readonly GalleryRunner runner;
    readonly TextBox directory = new TextBox(), details = new TextBox();
    readonly Label stateLabel = new Label();
    readonly Label replayStatus = new Label();
    readonly Button replay = new Button();
    readonly Button choose = new Button(), closeLegacy = new Button();
    bool working, canClose, replayRunning;
    public bool IsApplying { get; private set; }

    public GalleryPanel(bool inspectOnly) : this(inspectOnly, new GalleryRunner(AppDomain.CurrentDomain.BaseDirectory)) { }

    internal GalleryPanel(bool inspectOnly, GalleryRunner setup)
    {
        readOnly = inspectOnly;
        runner = setup;
        Font = new Font("Microsoft YaHei UI", 10);
        Dock = DockStyle.Fill;
        BackColor = Color.FromArgb(246, 247, 250);
        Controls.Add(new Label { Text = "剧情回放", Font = new Font(Font.FontFamily, 16, FontStyle.Bold),
            Location = new Point(24, 23), AutoSize = true });
        Controls.Add(new Label { Text = "选择游戏安装目录后，可在独立回放窗口观看原作演出。", Location = new Point(26, 65), AutoSize = true });
        Controls.Add(new Label { Text = "游戏安装目录", Location = new Point(26, 105), AutoSize = true });
        directory.Name = "galleryDirectory";
        directory.ReadOnly = true;
        directory.SetBounds(26, 132, 547, 28);
        Controls.Add(directory);
        choose.Name = "galleryChoose";
        choose.Text = "选择目录…";
        choose.SetBounds(586, 129, 106, 33);
        Controls.Add(choose);
        replay.Name = "storyReplay";
        replay.Text = "原作剧情回放";
        replay.SetBounds(26, 179, 180, 44);
        replay.Font = new Font(Font.FontFamily, 12, FontStyle.Bold);
        replay.BackColor = Color.FromArgb(220, 239, 229);
        replay.FlatStyle = FlatStyle.Flat;
        replay.Enabled = false;
        Controls.Add(replay);
        replayStatus.Text = readOnly ? "当前为只读检查模式。" : "首次打开会建立独立游戏副本。";
        replayStatus.SetBounds(222, 180, 470, 64);
        Controls.Add(replayStatus);
        Controls.Add(new Label { Name = "legacyGalleryHeading", Text = "V1.4 旧画廊",
            Font = new Font(Font.FontFamily, 13, FontStyle.Bold), Location = new Point(24, 269), AutoSize = true });
        Controls.Add(new Label { Text = "曾安装 V1.4 标题画廊的玩家可以在这里恢复原版标题画面。", Location = new Point(26, 305), AutoSize = true });
        stateLabel.Name = "galleryState";
        stateLabel.SetBounds(26, 349, 660, 35);
        stateLabel.Text = "等待读取旧画廊状态";
        stateLabel.Font = new Font(Font.FontFamily, 12, FontStyle.Bold);
        Controls.Add(stateLabel);
        closeLegacy.Name = "closeLegacyGallery";
        closeLegacy.Text = "关闭旧画廊";
        closeLegacy.Enabled = false;
        closeLegacy.SetBounds(26, 391, 146, 39);
        Controls.Add(closeLegacy);
        details.ReadOnly = true;
        details.Multiline = true;
        details.ScrollBars = ScrollBars.Vertical;
        details.BackColor = Color.White;
        details.SetBounds(26, 451, 666, 116);
        Controls.Add(details);
        directory.TextChanged += delegate { canClose = false; UpdateButtons(); };
        replay.Click += async delegate
        {
            if (readOnly || replayRunning || IsApplying) return;
            string game = directory.Text;
            replayRunning = true;
            UpdateButtons();
            replayStatus.Text = "正在打开回放窗口…";
            try
            {
                await Task.Run(() => runner.RunReplay(game));
                if (!IsDisposed) replayStatus.Text = "回放启动器已结束。";
            }
            catch (Exception error)
            {
                if (!IsDisposed)
                {
                    replayStatus.Text = "回放启动失败。";
                    MessageBox.Show(this, error.Message, "原作剧情回放", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
            }
            finally { replayRunning = false; if (!IsDisposed) UpdateButtons(); }
        };
        choose.Click += async delegate
        {
            using (var dialog = new FolderBrowserDialog { Description = "选择包含 Annihilated.exe 的游戏安装目录",
                ShowNewFolderButton = false })
            {
                if (Directory.Exists(directory.Text)) dialog.SelectedPath = directory.Text;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                directory.Text = dialog.SelectedPath;
            }
            await ReadOrClose(false, true);
        };
        closeLegacy.Click += async delegate { await ReadOrClose(true, false); };
    }

    public Task RefreshState() { return ReadOrClose(false, false); }

    void UpdateButtons()
    {
        replay.Enabled = !readOnly && !replayRunning && !IsApplying && GalleryLocation.IsGameDirectory(directory.Text);
        closeLegacy.Enabled = !readOnly && !working && !replayRunning && canClose;
        choose.Enabled = !working && !replayRunning;
    }

    async Task ReadOrClose(bool close, bool remember)
    {
        if (working || (close && (readOnly || replayRunning || !canClose))) return;
        working = true;
        IsApplying = close;
        canClose = false;
        UpdateButtons();
        stateLabel.Text = close ? "正在恢复原版标题画面…" : "正在读取旧画廊状态…";
        details.Text = "";
        try
        {
            string game = directory.Text;
            if (String.IsNullOrWhiteSpace(game))
            {
                game = await Task.Run(() => GalleryLocation.Find(
                    GalleryLocation.ReadChoice(GalleryLocation.ChoicePath), GalleryLocation.SteamRoots()));
                if (IsDisposed) return;
                directory.Text = game ?? "";
            }
            if (String.IsNullOrWhiteSpace(game))
            {
                stateLabel.Text = "尚未找到游戏";
                details.Text = "点击“选择目录…”，选择包含 Annihilated.exe 的文件夹。";
                return;
            }
            if (remember && GalleryLocation.IsGameDirectory(game))
            {
                try { GalleryLocation.SaveChoice(GalleryLocation.ChoicePath, game); }
                catch (Exception error) { details.Text = "本次目录已选定，下次需重新选择。" + error.Message + Environment.NewLine; }
            }
            GalleryStatus status = await Task.Run(() => {
                if (!close) return runner.ReadStatus(game);
                runner.CloseLegacyGallery(game);
                return GalleryStatus.Disabled;
            });
            if (IsDisposed) return;
            canClose = status == GalleryStatus.Enabled;
            stateLabel.Text = canClose ? "旧画廊已启用" : "旧画廊已关闭";
            details.AppendText(canClose ? "关闭后，下次启动正式游戏时将显示原版标题画面。" : "当前安装使用原版标题画面。");
            if (readOnly) details.AppendText(Environment.NewLine + "当前为只读检查模式。");
        }
        catch (GalleryRecoveryRequired error)
        {
            if (IsDisposed) return;
            canClose = true;
            stateLabel.Text = "旧画廊需要恢复";
            details.Text = error.Message + (readOnly ? " 当前为只读检查模式。" : "");
        }
        catch (Exception error)
        {
            if (IsDisposed) return;
            stateLabel.Text = "旧画廊状态待确认";
            details.Text = error.Message;
        }
        finally
        {
            working = IsApplying = false;
            if (!IsDisposed) UpdateButtons();
        }
    }
}
