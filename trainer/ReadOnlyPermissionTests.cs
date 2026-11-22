using System;
using System.Reflection;
using System.Runtime.Serialization;
using System.Threading.Tasks;
using System.Windows.Forms;
using Trainer;

public class ReadOnlyPermissionTests
{
    const BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
    static int passed;
    static void Check(bool ok, string message) { if (!ok) throw new Exception(message); passed++; }
    static void Set(object obj, string field, object value) { obj.GetType().GetField(field, Fields).SetValue(obj, value); }
    static void Buttons(TrainerWindow window) { typeof(TrainerWindow).GetMethod("SetEnabled", Fields).Invoke(window, null); }
    static bool Enabled(TrainerWindow window, string name) { return ((Button)typeof(TrainerWindow).GetField(name, Fields).GetValue(window)).Enabled; }
    static Control Find(TrainerWindow window, string name)
    {
        var controls = window.Controls.Find(name, true);
        Check(controls.Length == 1, "missing shared currency control: " + name);
        return controls[0];
    }

    [STAThread] public static int Main()
    {
        var remote = (Remote)FormatterServices.GetUninitializedObject(typeof(Remote));
        Set(remote, "Safety", new SessionSafety());
        Set(remote, "<StaticEnvelopeValidated>k__BackingField", true);
        var bridge = (Bridge)FormatterServices.GetUninitializedObject(typeof(Bridge));
        Set(bridge, "Remote", remote);
        Set(bridge, "runtimeValidated", true);
        foreach (bool readOnly in new[] { false, true })
        using (var window = new TrainerWindow(readOnly, true))
        {
            Set(window, "bridge", bridge);
            var currency = (NumericUpDown)Find(window, "curseAmount");
            var apply = (Button)Find(window, "applyCurse");
            var status = (Label)Find(window, "curseBalance");
            var show = typeof(TrainerWindow).GetMethod("ShowCurrency", Fields);
            Action<bool> display = fill => { show.Invoke(window, new object[] { fill }); Buttons(window); };
            Set(bridge, "<CurrencyBalance>k__BackingField", null);
            display(true);
            Check(!currency.Enabled && !apply.Enabled && status.Text.Contains("不可用"), "only unavailable currency disabled");
            Check(Enabled(window, "heal") == !readOnly && Enabled(window, "restore") == !readOnly && Enabled(window, "refresh"),
                  "unknown content and readonly preserve existing permissions");
            Set(bridge, "<CurrencyBalance>k__BackingField", 0m);
            display(true);
            Check(currency.Enabled == !readOnly && apply.Enabled == !readOnly && currency.Value == 0m, "zero and readonly currency permissions");
            currency.Value = 20;
            Set(bridge, "<CurrencyBalance>k__BackingField", 32m);
            display(false);
            Check(currency.Value == 20 && status.Text.Contains("32"), "auto refresh preserves unfinished input but reports fresh balance");
            display(true);
            Check(currency.Value == 32, "explicit refresh adopts the current balance");
            Set(bridge, "<CurrencyBalance>k__BackingField", 24730990m);
            display(true);
            Check(currency.Value == 24730990m && !apply.Enabled, "natural balances above input limit are displayed without truncation");
            currency.Value = 300000m;
            Check(apply.Enabled == !readOnly, "can explicitly replace a high balance with a supported value");
            if (!readOnly)
            {
                var hero = new Character { Id = "partner", CharacterKey = "hero", Level = 46, Health = 236, MaxHealth = 269, Sanity = 30 };
                typeof(TrainerWindow).GetMethod("ShowTeam", Fields).Invoke(window, new object[] { new[] { hero }, true, null, false, false });
                var exceptionType = typeof(Bridge).Assembly.GetType("Trainer.SanityReadbackException");
                Check(exceptionType != null, "a game-maintained companion SAN must keep the session usable");
                var rejected = (Exception)Activator.CreateInstance(exceptionType, new object[] { "partner", "hero", 29, 30 });
                Func<Character[]> action = () => { throw rejected; };
                var operation = (Task)typeof(TrainerWindow).GetMethod("Operate", Fields).Invoke(window,
                    new object[] { "unreachable success", action, false, "partner", true, false, false });
                while (!operation.IsCompleted) { Application.DoEvents(); System.Threading.Thread.Sleep(1); }
                operation.GetAwaiter().GetResult();
                Check(Enabled(window, "heal") && apply.Enabled, "game-maintained SAN must keep other writes available");
                var log = (TextBox)typeof(TrainerWindow).GetField("history", Fields).GetValue(window);
                Check(log.Text.Contains("勇者") && log.Text.Contains("29") && log.Text.Contains("30") && !log.Text.Contains("unreachable success"),
                      "report requested and retained SAN without claiming a change");
            }
            Set(window, "bridge", null);
        }
        Console.WriteLine("PASS " + passed + " readonly/UI permission assertions");
        return 0;
    }
}
