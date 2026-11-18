using System;
using System.Reflection;
using System.Windows.Forms;

class UiTests
{
    static int passed;

    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
        passed++;
    }

    [STAThread]
    static void Main()
    {
        var assembly = Assembly.LoadFrom("Trainer.exe");
        var windowType = assembly.GetType("TrainerWindow");
        using (var form = (Form)Activator.CreateInstance(windowType))
        {
            Check(form.Text.Contains("v1.4"), "version");
            var tabs = (TabControl)form.Controls[0];
            var tabHandle = tabs.Handle;
            Check(tabs.TabPages.Count == 3, "CG tab present alongside the two existing tabs");
            Check(tabs.SelectedIndex == 0, "standard startup opens role and battle");
            Check(tabs.TabPages[1].Text.Contains("剧透"), "spoiler tab");
            var saves = tabs.TabPages[1].Controls[0];
            Check(saves is UserControl, "save panel");
            Check(saves.Controls.Count >= 2, "warning and gate");
            foreach (Control control in saves.Controls)
                if (control is Panel) Check(control.Enabled, "save operations container enabled");
            Check(tabs.TabPages[0].Controls.Count > 10, "existing UI retained");
            Check(tabs.TabPages[2].Text.Contains("CG"), "gallery discoverable by name");
        }
        using (var form = (Form)Activator.CreateInstance(windowType, new object[] { false, false, true }))
        {
            var tabs = (TabControl)form.Controls[0];
            var tabHandle = tabs.Handle;
            Check(tabs.SelectedIndex == 2, "gallery-only startup opens the CG tab");
            var gallery = tabs.SelectedTab;
            Check(gallery.Controls.Find("galleryChoose", true)[0].Enabled, "can choose a folder without connecting");
            Check(!gallery.Controls.Find("galleryToggle", true)[0].Enabled, "must verify status before enabling");
        }
        Console.WriteLine("PASS " + passed + " UI structure assertions");
    }
}
