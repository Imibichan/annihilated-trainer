using System;
using Trainer;
public class GrowthTests {
 public static int Main(){try{
  var t=typeof(Remote).Assembly.GetType("Trainer.GrowthRules");Check(t!=null,"growth-preserving rules are missing");
  Check((int)Call(t,"BonusFor",100,32)==68,"store desired minus normal");
  Check((int)Call(t,"BonusFor",0,32)==-32,"support lowering attributes");
  Check((int)Call(t,"BonusFor",34,34)==0,"restore removes bonus at current level");
  Check((int)Call(t,"Desired",34,68)==102,"level growth adds on modified starting point");
  Check((int)Call(t,"Desired",34,-32)==2,"negative bonus still allows growth");
  Check((int?)Call(t,"Correction",34,34,68)==102,"correct raw recalculation once");
  Check(Call(t,"Correction",102,34,68)==null,"do not compound bonus");
  Check(Call(t,"Correction",777,34,68)==null,"do not overwrite unrelated story values");
  Check(Call(t,"Correction",34,34,0)==null,"normal attributes need no writes");
  var compute=t.GetMethod("Compute");
  CheckArray((int[])compute.Invoke(null,new object[]{"player",42,new int[]{6,6,6,6},false,false,""}),new[]{32,32,32,32},"player42 matches real save");
  CheckArray((int[])compute.Invoke(null,new object[]{"player",44,new int[]{8,7,7,7},false,false,""}),new[]{34,34,34,34},"player44 matches real save");
  CheckArray((int[])compute.Invoke(null,new object[]{"mage",42,new int[4],false,true,""}),new[]{22,52,62,356},"powered mage42 matches real save");
  CheckArray((int[])compute.Invoke(null,new object[]{"mage",44,new int[4],false,true,""}),new[]{22,54,65,366},"powered mage44 matches real save");
  CheckArray((int[])compute.Invoke(null,new object[]{"mage",44,new int[4],false,true,"demonLord"}),new[]{22,54,65,183},"preserve game boss-specific scaling");
  CheckArray((int[])compute.Invoke(null,new object[]{"hero",9,new int[4],true,false,""}),new[]{47,14,13,47},"true hero variant");
  Check((string)Call(t,"BonusKey","mage","Str")=="GPTToolsStat_mage_Str","bonuses follow character identity");
  Check(typeof(Bridge).GetMethod("Apply").GetParameters()[1].ParameterType==typeof(string),"apply must bind to the character shown when clicked");
  var content=typeof(Remote).GetMethod("IsSupportedContent");Check(content!=null,"resource classification API remains available");
  Check(!(bool)content.Invoke(null,new object[]{"unknown"}),"unlisted resources remain classified as unknown");
  Check((bool)content.Invoke(null,new object[]{"b9254bd24d0daef581f2186fa1da77c5"}),"recognized resources retain their classification");
  Console.WriteLine("PASS 21 growth assertions");return 0;
 }catch(Exception e){Console.WriteLine("FAIL growth: "+e.Message);return 1;}}
 static object Call(Type t,string n,params object[] a){return t.GetMethod(n).Invoke(null,a);}
 static void Check(bool ok,string s){if(!ok)throw new Exception(s);}
 static void CheckArray(int[] a,int[] b,string s){for(int i=0;i<4;i++)Check(a[i]==b[i],s+" index="+i+" actual="+a[i]+" expected="+b[i]);}
}
