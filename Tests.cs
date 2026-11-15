using System;
using Trainer;
public class Tests {
 public static int Main() {
  try {
   Check(Rules.Heal(20,101)==70,"odd maximum rounds down");
   Check(Rules.Heal(90,100)==100,"cap full health");
   Check(Rules.Heal(100,100)==100,"already full");
   Check(Rules.Heal(0,100)==0,"do not revive defeated role");
   Check(!Rules.ValidStat(-1),"reject negative stat");
   Check(!Rules.ValidStat(1000000),"reject excessive stat");
   Check(Rules.ValidStat(366),"accept existing stat");
   Check(typeof(Dispatcher).GetMethod("RootString").ReturnType==typeof(long),"Unity 6 GC handles must preserve all 64 bits");
   Check(typeof(Dispatcher).GetMethod("Target").GetParameters()[0].ParameterType==typeof(long),"GC target lookup accepts 64-bit handle");
   Check(typeof(Dispatcher).GetMethod("Unroot").GetParameters()[0].ParameterType==typeof(long),"GC handle release accepts 64-bit handle");
   var gate=typeof(Remote).GetMethod("IsSupportedBuild");Check(gate!=null,"unknown game builds must be rejected before runtime calls");
   Check(!(bool)gate.Invoke(null,new object[]{"unknown"}),"reject unknown build");
   Check((bool)gate.Invoke(null,new object[]{"38F5ADA37FEC235248A61971C06E4ACCF4C95A74B5C74FCCBE32412AB04C26F1"}),"accept verified build");
   var safetyType=typeof(Remote).Assembly.GetType("Trainer.SessionSafety");Check(safetyType!=null,"uncertain calls need explicit allocation lifetime state");
   var safety=Activator.CreateInstance(safetyType);Check((bool)safetyType.GetProperty("MayRelease").GetValue(safety,null),"normal completed calls can release allocations");
   safetyType.GetMethod("MarkUncertain").Invoke(safety,null);Check(!(bool)safetyType.GetProperty("MayRelease").GetValue(safety,null),"timed-out calls retain all inputs until process exit");
   Console.WriteLine("PASS 16 assertions"); return 0;
  } catch(Exception e) { Console.WriteLine("FAIL: "+e.Message); return 1; }
 }
 static void Check(bool b,string s){if(!b)throw new Exception(s);}
}
