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
    readonly Button choose = new Button(), refresh = new Button(), toggle = new Button(), update = new Button();
    bool? enabled;
    bool working, recovery;
    public bool IsApplying { get; private set; }

    public GalleryPanel(bool inspectOnly) : this(inspectOnly, new GalleryRunner(AppDomain.CurrentDomain.BaseDirectory)) { }

    internal GalleryPanel(bool inspectOnly, GalleryRunner setup)
    {
        readOnly = inspectOnly;
        runner = setup;
        Font = new Font("Microsoft YaHei UI", 10);
        Dock = DockStyle.Fill;
        BackColor = Color.FromArgb(246, 247, 250);
        Controls.Add(new Label { Text = "标题画面的 CG 画廊", Font = new Font(Font.FontFamily, 16, FontStyle.Bold),
            Location = new Point(24, 23), AutoSize = true });
        Controls.Add(new Label { Text = "启用后，下次启动游戏时可从标题画面进入画廊。关闭后入口会在下次启动时消失。",
            Location = new Point(26, 68), Size = new Size(656, 44) });
        Controls.Add(new Label { Text = "游戏安装目录", Location = new Point(26, 126), AutoSize = true });
        directory.Name = "galleryDirectory";
        directory.ReadOnly = true;
        directory.SetBounds(26, 154, 547, 28);
        Controls.Add(directory);
        choose.Name = "galleryChoose";
        choose.Text = "选择目录…";
        choose.SetBounds(586, 151, 106, 33);
        Controls.Add(choose);
        stateLabel.Name = "galleryState";
        stateLabel.SetBounds(26, 215, 660, 35);
        stateLabel.Text = "尚未读取画廊状态";
        stateLabel.Font = new Font(Font.FontFamily, 12, FontStyle.Bold);
        Controls.Add(stateLabel);
        toggle.Name = "galleryToggle";
        toggle.Text = "启用画廊";
        toggle.Enabled = false;
        toggle.SetBounds(26, 257, 146, 39);
        Controls.Add(toggle);
        refresh.Text = "重新读取";
        refresh.SetBounds(185, 257, 122, 39);
        Controls.Add(refresh);
        update.Name = "galleryUpdate";
        update.Text = "更新画廊";
        update.Visible = update.Enabled = false;
        update.SetBounds(320, 257, 122, 39);
        Controls.Add(update);
        details.ReadOnly = true;
        details.Multiline = true;
        details.ScrollBars = ScrollBars.Vertical;
        details.BackColor = Color.White;
        details.SetBounds(26, 320, 666, 116);
        Controls.Add(details);
        choose.Click += async delegate
        {
            using (var dialog = new FolderBrowserDialog { Description = "选择包含 Annihilated.exe 的游戏安装目录",
                ShowNewFolderButton = false })
            {
                if (Directory.Exists(directory.Text)) dialog.SelectedPath = directory.Text;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                directory.Text = dialog.SelectedPath;
            }
            await ReadOrApply(null, true);
        };
        refresh.Click += async delegate { await ReadOrApply(null, false); };
        update.Click += async delegate { if (!readOnly) await ReadOrApply(true, false); };
        toggle.Click += async delegate
        {
            if (readOnly) return;
            if (recovery) await ReadOrApply(false, false);
            else if (enabled.HasValue) await ReadOrApply(!enabled.Value, false);
        };
    }

    public Task RefreshState() { return ReadOrApply(null, false); }

    async Task ReadOrApply(bool? target, bool remember)
    {
        if (working) return;
        working = true;
        bool restore = recovery && target == false;
        recovery = false;
        IsApplying = target.HasValue;
        enabled = null;
        choose.Enabled = refresh.Enabled = toggle.Enabled = false;
        update.Visible = update.Enabled = false;
        stateLabel.Text = target.HasValue ? "正在应用设置并核验安装状态…" : "正在读取安装状态…";
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
            GalleryStatus status = await Task.Run(() =>
            {
                if (!target.HasValue) return runner.ReadStatus(game);
                if (restore) runner.Recover(game);
                else runner.SetEnabled(game, target.Value);
                return target.Value ? GalleryStatus.Enabled : GalleryStatus.Disabled;
            });
            if (IsDisposed) return;
            bool installed = status != GalleryStatus.Disabled;
            enabled = installed;
            stateLabel.Text = installed ? "画廊已启用" : "画廊已关闭";
            toggle.Text = installed ? "关闭画廊" : "启用画廊";
            details.Text = installed ? "下次启动游戏，标题画面将显示 CG 画廊入口。" : "下次启动游戏，标题画面将使用原有菜单。";
            if (status == GalleryStatus.UpdateAvailable)
            {
                stateLabel.Text = "画廊已启用 · 有可用更新";
                details.Text = "画廊工具或游戏素材已有变化。点击“更新画廊”，使用当前游戏资源重新生成，下一次启动游戏时生效。";
                update.Visible = true;
                update.Enabled = !readOnly;
            }
            if (readOnly) details.AppendText(Environment.NewLine + "当前为只读检查模式。");
            if (remember)
            {
                try { GalleryLocation.SaveChoice(GalleryLocation.ChoicePath, game); }
                catch (Exception error) { details.AppendText(Environment.NewLine + "本次目录已选定，下次需重新选择。" + error.Message); }
            }
        }
        catch (GalleryRecoveryRequired error)
        {
            if (IsDisposed) return;
            recovery = true;
            stateLabel.Text = "画廊需要恢复";
            toggle.Text = "恢复原始画面";
            details.Text = error.Message + (readOnly ? " 当前为只读检查模式。" : "");
        }
        catch (Exception error)
        {
            if (IsDisposed) return;
            stateLabel.Text = "画廊状态待确认";
            details.Text = error.Message;
        }
        finally
        {
            if (!IsDisposed)
            {
                choose.Enabled = refresh.Enabled = true;
                toggle.Enabled = !readOnly && (enabled.HasValue || recovery);
            }
            working = IsApplying = false;
        }
    }
}
