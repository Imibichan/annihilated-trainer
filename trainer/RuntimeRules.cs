using System;namespace Trainer{public static class RuntimeRules{
public static bool Schema(bool servicesStatic,string servicesType,int mapOffset,string getReturn,string getArg,string setReturn,string[] setArgs){return servicesStatic&&servicesType=="System.Collections.Generic.List<Naninovel.IEngineService>"&&mapOffset>=16&&mapOffset<4096&&mapOffset%8==0&&getReturn=="System.String"&&getArg=="System.String"&&setReturn=="System.Void"&&setArgs!=null&&setArgs.Length==2&&setArgs[0]=="System.String"&&setArgs[1]=="System.String";}
static bool Identity(string id,string character){return id=="player"?character=="player":id=="partner"&&(character=="hero"||character=="warrior"||character=="mage"||character=="priest");}
public static bool Sanity(string id,string character,int sanity){return Identity(id,character)&&sanity>=-20&&sanity<=100;}
public static bool Health(string id,string character,int hp,int max){return Identity(id,character)&&max>0&&max<=100000000&&hp>=-100000000&&hp<=max;}
}}

namespace Trainer
{
    // Naninovel stores variable text. Seven decimal digits preserve integer precision
    // when the game's arithmetic formats a single-precision result for the next command.
    public static class CurseCurrency
    {
        public const string Key = "curse";
        public const int Maximum = 9999999;

        public static decimal? Read(Func<string, string> get)
        {
            string raw;
            try { raw = get(Key); }
            catch (GameVariableException) { return null; }
            decimal balance;
            return decimal.TryParse(raw, System.Globalization.NumberStyles.Float,
                       System.Globalization.CultureInfo.InvariantCulture, out balance)
                   && balance >= 0 && balance == decimal.Truncate(balance) ? balance : (decimal?)null;
        }

        public static decimal Apply(Func<string, string> get, Action<string, int> set, decimal expected, int desired)
        {
            if (desired < 0 || desired > Maximum)
                throw new InvalidOperationException("诅咒余额请输入 0～9,999,999 的整数。");
            decimal? current = Read(get);
            if (!current.HasValue)
                throw new InvalidOperationException("游戏中的诅咒余额缺失或格式异常。");
            if (current.Value != expected)
                throw new InvalidOperationException("游戏中的诅咒余额已变化，请核对当前余额后再应用。");
            if (current.Value != desired) set(Key, desired);
            decimal? confirmed = Read(get);
            if (confirmed != desired)
                throw new InvalidOperationException("游戏读回的诅咒余额与输入不一致，请重新读取。");
            return confirmed.Value;
        }
    }

    sealed class GameVariableException : Exception
    {
        public GameVariableException(string message) : base(message) { }
    }

    sealed class CurrencyOperationException : InvalidOperationException
    {
        public CurrencyOperationException(Exception cause) : base(cause.Message, cause) { }
    }
}
