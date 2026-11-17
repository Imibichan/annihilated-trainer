using System;
namespace Trainer {
// Mirrors StatusFunc.StatusParameters/CalculateStatusValue from the verified local game build.
public static class GrowthRules {
 public static readonly string[] Characters={"player","hero","warrior","mage","priest"};
 public static readonly string[] Stats={"Str","Dex","Agi","Mag"};
 public static string BonusKey(string character,string stat){if(Array.IndexOf(Characters,character)<0||Array.IndexOf(Stats,stat)<0)throw new Exception("无法识别人物或属性，未执行额外加成修改。");return "GPTToolsStat_"+character+"_"+stat;}
 public static int BonusFor(int desired,int normal){if(!Rules.ValidStat(desired))throw new Exception("四维请输入 0～99999 的整数。");return checked(desired-normal);}
 public static int Desired(int normal,int bonus){long result=(long)normal+bonus;if(result<0||result>99999)throw new Exception("成长后的属性超出 0～99999 支持范围。");return (int)result;}
 public static int? Correction(int current,int normal,int bonus){long target=(long)normal+bonus;if(bonus==0||current!=normal||target==current||target<0||target>99999)return null;return (int)target;}
 public static int[] Compute(string character,int level,int[] growth,bool trueHero,bool poweredMage,string battleTarget){
  if(level<0||growth==null||growth.Length!=4)throw new Exception("无法识别等级或成长数据。");
  double[] rate,initial=new double[4];
  switch(character){
   case "player":rate=new[]{0.5,0.5,0.5,0.5};initial=new[]{4.0,4.0,4.0,4.0};break;
   case "hero":rate=trueHero?new[]{1.7,1.4,1.3,1.7}:new[]{1.5,0.6,0.7,1.25};initial=trueHero?new[]{30.0,0.0,0.0,30.0}:new[]{3.0,0.0,0.0,3.0};break;
   case "warrior":rate=new[]{0.25,1.47,0.8,0.8};initial[1]=2;break;
   case "mage":rate=poweredMage?new[]{0.5,1.2,1.4,battleTarget=="demonLord"?2.4:4.8}:new[]{0.3,0.9,1.2,0.0};initial[2]=2;if(poweredMage)initial[3]=battleTarget=="demonLord"?75:150;break;
   case "priest":rate=new[]{0.9,1.1,0.6,1.5};break;
   default:throw new Exception("当前人物不在已验证成长公式中："+character);
  }
  var result=new int[4];for(int i=0;i<4;i++){double value=Math.Round(rate[i]*((double)level+1)+growth[i]+initial[i],MidpointRounding.ToEven);result[i]=(int)Math.Max(0,Math.Min(int.MaxValue,value));}return result;
 }
}
public sealed class GrowthUpdate {public Character[] Team;public bool Changed;}
}

namespace Trainer { public static class RoleRules { public static string Label(string key){switch(key){case "player":return "主角";case "hero":return "勇者";case "warrior":return "战士";case "mage":return "魔法师";case "priest":return "僧侣";default:return "未知角色";}} public static bool ValidSanity(int value){return value>=-20 && value<=100;} } }
