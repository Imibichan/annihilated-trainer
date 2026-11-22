using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using Trainer;

public class CurrencyTests
{
    static int passed;
    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
        passed++;
    }

    static void Reject(Action operation, string message)
    {
        try { operation(); }
        catch (InvalidOperationException) { passed++; return; }
        throw new Exception(message);
    }

    public static int Main()
    {
        var vars = new Dictionary<string, string> { { "curseCount", "713" } };
        Func<string, string> getter = key => vars.ContainsKey(key) ? vars[key] : null;
        int writes = 0;
        Action<string, int> setter = (k, v) => { vars[k] = v.ToString(CultureInfo.InvariantCulture); writes++; };
        Func<decimal?> balance = () => CurseCurrency.Read(getter);
        Func<decimal, int, decimal> update = (expected, desired) => CurseCurrency.Apply(getter, setter, expected, desired);
        Check(balance() == null, "missing balance must be unavailable");
        Reject(() => update(0, 60), "must not create missing currency");
        foreach (var invalid in new[] { "", "no", "-2", "1.25", "NaN" })
        {
            vars["curse"] = invalid;
            Check(balance() == null, "invalid currency must stay unavailable");
        }
        vars["curse"] = "2.473099E+07";
        Check(balance() == 24730990m, "display high native integer balances in exponent format");
        vars["curse"] = "216845";
        Check(update(216845, 300001) == 300001m && vars["curse"] == "300001", "write and read spendable balance");
        Reject(() => update(216845, 0), "reject stale balance");
        Check(vars["curse"] == "300001", "stale balance cannot overwrite a new value");
        Check(update(300001, 0) == 0 && balance() == 0, "zero is valid");
        Check(update(0, 0) == 0 && writes == 2, "identical balance is read back without a write");
        Check(update(0, 9999999) == 9999999, "maximum exact input accepted");
        Reject(() => update(9999999, -1), "negative input rejected");
        Reject(() => update(9999999, 10000000), "excessive input rejected");
        Check(vars.Count == 2 && vars["curseCount"] == "713" && writes == 3, "cumulative counter untouched");
        setter = (k, v) => vars[k] = "8";
        Reject(() => update(9999999, 13), "mismatched readback must never report success");
        var allow = typeof(Bridge).GetMethod("Allowed", BindingFlags.NonPublic | BindingFlags.Static);
        Check((bool)allow.Invoke(null, new object[] { "curse" }) && !(bool)allow.Invoke(null, new object[] { "curseCount" }),
              "write allowlist must permit only the spendable field");

        var folder = Directory.CreateDirectory(Path.Combine(Path.GetTempPath(), "OrienCurrency-" + Guid.NewGuid().ToString("N")));
        try
        {
            var exe = Path.Combine(folder.FullName, "Annihilated.exe");
            File.WriteAllText(exe, "");
            Check(!Remote.IsReplayExecutable(exe), "ordinary game is eligible");
            File.WriteAllText(Path.Combine(folder.FullName, ".orien-replay-copy.json"), "{}");
            Check(Remote.IsReplayExecutable(exe), "private replay is excluded");
        }
        finally { folder.Delete(true); }
        Console.WriteLine("PASS " + passed + " shared currency and replay selection assertions");
        return 0;
    }
}
