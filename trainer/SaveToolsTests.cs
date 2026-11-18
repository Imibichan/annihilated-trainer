using System;
using System.IO;
using System.Linq;
using System.IO.Compression;
using System.Text;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using Trainer;
public static class SaveToolsTests {
 static int count; static string root,live,backups; static JavaScriptSerializer json=new JavaScriptSerializer { MaxJsonLength=16000000 };
 static void Check(bool ok,string name){if(!ok)throw new Exception("FAIL "+name);Console.WriteLine("PASS "+name);count++;}
 static void Throws(Action a,string name){try{a();}catch{Check(true,name);return;}throw new Exception("FAIL expected rejection: "+name);}
 static string ReadRaw(string p){using(var f=File.OpenRead(p))using(var z=new DeflateStream(f,CompressionMode.Decompress))using(var r=new StreamReader(z,Encoding.UTF8,true))return r.ReadToEnd();}
 static Dictionary<string,object> Decode(string p){return json.Deserialize<Dictionary<string,object>>(ReadRaw(p));}
 static void WriteRaw(string p,string text){using(var f=File.Create(p))using(var z=new DeflateStream(f,CompressionMode.Compress))using(var w=new StreamWriter(z,new UTF8Encoding(true)))w.Write(text);}
 public static int Main(string[] args){try {
 root=Path.Combine(Path.GetTempPath(),"TrainerSaveTests-"+Guid.NewGuid().ToString("N"));live=Path.Combine(root,"fixtures");backups=Path.Combine(root,"snapshots");Directory.CreateDirectory(live);
 string fixture=args.Length>0?args[0]:Environment.GetEnvironmentVariable("ANNIHILATED_SAVE_FIXTURE");
 if(String.IsNullOrWhiteSpace(fixture))throw new ArgumentException("请通过 ANNIHILATED_SAVE_FIXTURE 指定测试存档副本目录。");
 foreach(var p in Directory.GetFiles(fixture))File.Copy(p,Path.Combine(live,Path.GetFileName(p)));
 string global=Path.Combine(live,"GlobalSave.nson");var old=File.ReadAllBytes(global);var oldText=ReadRaw(global);
 var info=SaveTools.Inspect(live);Check(info.LoopCount==10&&info.HeroClears==0&&info.MageClears==1&&info.WarriorClears==0,"decode real fixture counters");Check(!info.Eligible,"fixture ineligible");
 string backup=SaveTools.Backup(live,backups);Check(File.ReadAllBytes(Path.Combine(backup,"files","GlobalSave.nson")).SequenceEqual(old),"backup byte exact");
 var other=Directory.GetFiles(live).Where(p=>Path.GetFileName(p)!="GlobalSave.nson").ToDictionary(p=>Path.GetFileName(p),p=>File.ReadAllBytes(p));
 string repairBackup=SaveTools.RepairEligibility(live,backups,info.GlobalHash);var changed=SaveTools.Inspect(live);Check(changed.Eligible&&changed.LoopCount==7,"minimal eligibility repair");Check(File.ReadAllBytes(Path.Combine(repairBackup,"files","GlobalSave.nson")).SequenceEqual(old),"repair backed up original");
 foreach(var kv in other)Check(File.ReadAllBytes(Path.Combine(live,kv.Key)).SequenceEqual(kv.Value),"unchanged "+kv.Key);
 var before=json.Deserialize<Dictionary<string,object>>(oldText);var after=Decode(global);var bm=(Dictionary<string,object>)before["objectJsonMap"];var am=(Dictionary<string,object>)after["objectJsonMap"];var bk=(System.Collections.ArrayList)bm["keys"];var bv=(System.Collections.ArrayList)bm["values"];var av=(System.Collections.ArrayList)am["values"];
 for(int i=0;i<bk.Count;i++){if(!((string)bk[i]).StartsWith("Naninovel.CustomVariableManager+GlobalState,"))Check((string)bv[i]==(string)av[i],"unrelated outer state "+i);else {var x=json.Deserialize<Dictionary<string,object>>((string)bv[i]);var y=json.Deserialize<Dictionary<string,object>>((string)av[i]);var xm=(Dictionary<string,object>)x["GlobalVariableMap"];var ym=(Dictionary<string,object>)y["GlobalVariableMap"];var keys=(System.Collections.ArrayList)xm["keys"];var vals=(System.Collections.ArrayList)xm["values"];var nvals=(System.Collections.ArrayList)ym["values"];for(int j=0;j<keys.Count;j++)if(!new[]{"G_gameLoopCount","G_gameClearHeroCount","G_gameClearMageCount","G_gameClearWarriorCount"}.Contains((string)keys[j]))Check((string)vals[j]==(string)nvals[j],"unrelated global "+keys[j]);}}
 Throws(()=>SaveTools.RepairEligibility(live,backups,info.GlobalHash),"stale inspect refused");
 var repairedBytes=File.ReadAllBytes(global);int backupCount=Directory.GetDirectories(backups).Length;
 Check(SaveTools.RepairEligibility(live,backups,changed.GlobalHash)==null,"eligible repair no-op result");
 Check(File.ReadAllBytes(global).SequenceEqual(repairedBytes)&&Directory.GetDirectories(backups).Length==backupCount,"eligible no-op leaves bytes and backups untouched");
 string extra=Path.Combine(live,"ExtraProgress.bin");File.WriteAllText(extra,"preserve in protective snapshot");string protective=SaveTools.Restore(live,backup,backups);Check(File.ReadAllBytes(global).SequenceEqual(old),"restore byte exact");Check(!File.Exists(extra)&&File.Exists(Path.Combine(protective,"files","ExtraProgress.bin")),"restore removes extra only after protective backup");
 File.AppendAllText(Path.Combine(backup,"files","GlobalSave.nson"),"corrupt");Throws(()=>SaveTools.Restore(live,backup,backups),"corrupt backup refused");Check(File.ReadAllBytes(global).SequenceEqual(old),"failed restore leaves current untouched");
 Throws(()=>SaveTools.Backup(live,Path.Combine(live,"nested")),"nested backup refused");
 WriteRaw(global,oldText.Replace("G_gameClearHeroCount","UnknownCounter"));Throws(()=>SaveTools.Inspect(live),"missing counter rejected");
 WriteRaw(global,oldText.Replace("G_gameClearHeroCount","G_gameLoopCount"));Throws(()=>SaveTools.Inspect(live),"duplicate counter rejected");
 File.WriteAllBytes(global,new byte[]{1,2,3});Throws(()=>SaveTools.Inspect(live),"corrupt nson rejected");
  string recoveredBackup=SaveTools.Restore(live,repairBackup,backups);
 Check(File.ReadAllBytes(global).SequenceEqual(old),"restore can recover corrupt current global");
 Check(File.ReadAllBytes(Path.Combine(recoveredBackup,"files","GlobalSave.nson")).SequenceEqual(new byte[]{1,2,3}),"corrupt original protected byte exact");
 string validBackup=SaveTools.Backup(live,backups);
 string manifest=Path.Combine(validBackup,"manifest.json");string manifestText=File.ReadAllText(manifest);
 File.WriteAllText(manifest,manifestText.Replace("\"formatVersion\":1","\"formatVersion\":2"));
 Throws(()=>SaveTools.Restore(live,validBackup,backups),"unknown backup version rejected");
 File.WriteAllText(manifest,manifestText.Replace("GlobalSave.nson","../GlobalSave.nson"));
 Throws(()=>SaveTools.Restore(live,validBackup,backups),"manifest traversal rejected");
 File.WriteAllText(manifest,manifestText);File.WriteAllText(Path.Combine(validBackup,"files","extra.bin"),"bad");
 Throws(()=>SaveTools.Restore(live,validBackup,backups),"unmanifested backup file rejected");
 Check(File.ReadAllBytes(global).SequenceEqual(old),"all rejected restores leave current untouched");
  Check(SaveTools.DefaultBackupDirectory==Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AnnihilatedTrainer","Backups"),"backup default belongs to current user local app data");
 Check(SaveTools.DefaultSaveDirectory.EndsWith(Path.Combine("DeathKumiai","Annihilated","NaninovelData","Saves")),"default game save suffix");
 string portable=Path.Combine(root,"Other User 测试 空格","存档");Directory.CreateDirectory(portable);
 foreach(var f in Directory.GetFiles(live))File.Copy(f,Path.Combine(portable,Path.GetFileName(f)));
 string portableRoot=Path.Combine(root,"另一个 用户","备份 空格");
 Check(SaveTools.Inspect(portable).LoopCount==10,"alternate Unicode user save path");
 string portableBackup=SaveTools.Backup(portable,portableRoot);
 SaveTools.RepairEligibility(portable,portableRoot,SaveTools.Inspect(portable).GlobalHash);
 SaveTools.Restore(portable,portableBackup,portableRoot);
 Check(File.ReadAllBytes(Path.Combine(portable,"GlobalSave.nson")).SequenceEqual(old),"Unicode spaces backup repair restore roundtrip");
 string missing=Path.Combine(root,"missing directory");
 Throws(()=>SaveTools.Inspect(missing),"missing save directory rejected");
 Throws(()=>SaveTools.Restore(missing,portableBackup,portableRoot),"restore missing destination rejected");
 Check(!Directory.Exists(missing),"failed restore does not create missing destination");
 File.Delete(Path.Combine(portableBackup,"files","GameSave001.nson"));
 Throws(()=>SaveTools.Restore(portable,portableBackup,portableRoot),"missing backup file rejected");
 Check(File.ReadAllBytes(Path.Combine(portable,"GlobalSave.nson")).SequenceEqual(old),"missing backup file never changes current");
 File.Delete(Path.Combine(portable,"GlobalSave.nson"));
 Throws(()=>SaveTools.Backup(portable,portableRoot),"missing global save rejected");
 Throws(()=>SaveTools.Restore(portable,repairBackup,backups),"missing current global restore refused safely");
 Check(!File.Exists(Path.Combine(portable,"GlobalSave.nson")),"refused restore leaves missing global absent");
  Check(new EligibilityInfo{LoopCount=8}.Eligible,"eight remains eligible script threshold");
 Check(new EligibilityInfo{LoopCount=8}.NeedsRepair,"eight requires default-seven repair");
 Check(!new EligibilityInfo{LoopCount=7}.NeedsRepair,"seven requires no repair");
 Check(!new EligibilityInfo{LoopCount=3}.NeedsRepair,"lower loop requires no repair");
 Check(new EligibilityInfo{LoopCount=3,MageClears=1}.NeedsRepair,"clear counter requires repair at lower loop");
 string eightDir=Path.Combine(root,"eight-loop-fixture");Directory.CreateDirectory(eightDir);
 foreach(var f in Directory.GetFiles(live))File.Copy(f,Path.Combine(eightDir,Path.GetFileName(f)));
 string eightGlobal=Path.Combine(eightDir,"GlobalSave.nson");
 var eightOuter=Decode(eightGlobal);var eightMap=(Dictionary<string,object>)eightOuter["objectJsonMap"];
 var eightKeys=(System.Collections.ArrayList)eightMap["keys"];var eightValues=(System.Collections.ArrayList)eightMap["values"];
 int globalIndex=-1;for(int i=0;i<eightKeys.Count;i++)if(((string)eightKeys[i]).StartsWith("Naninovel.CustomVariableManager+GlobalState,"))globalIndex=i;
 var eightState=json.Deserialize<Dictionary<string,object>>((string)eightValues[globalIndex]);var eightVars=(Dictionary<string,object>)eightState["GlobalVariableMap"];
 var ek=(System.Collections.ArrayList)eightVars["keys"];var ev=(System.Collections.ArrayList)eightVars["values"];
 foreach(string k in new[]{"G_gameClearHeroCount","G_gameClearMageCount","G_gameClearWarriorCount"})ev[ek.IndexOf(k)]="0";
 ev[ek.IndexOf("G_gameLoopCount")]="8";eightValues[globalIndex]=json.Serialize(eightState);WriteRaw(eightGlobal,json.Serialize(eightOuter));
 var atEight=SaveTools.Inspect(eightDir);Check(atEight.Eligible&&atEight.NeedsRepair,"eight fixture eligible but repairable");
 Check(SaveTools.RepairEligibility(eightDir,backups,atEight.GlobalHash)!=null,"eight repair produces protective backup");
 Check(SaveTools.Inspect(eightDir).LoopCount==7,"eight repaired to seven");
 ev[ek.IndexOf("G_gameLoopCount")]="3";ev[ek.IndexOf("G_gameClearWarriorCount")]="2";eightValues[globalIndex]=json.Serialize(eightState);WriteRaw(eightGlobal,json.Serialize(eightOuter));
 SaveTools.RepairEligibility(eightDir,backups,SaveTools.Inspect(eightDir).GlobalHash);
 Check(SaveTools.Inspect(eightDir).LoopCount==3&&SaveTools.Inspect(eightDir).Eligible,"lower loop preserved when clearing other counters");
 Console.WriteLine("PASS TOTAL "+count+"; disposable fixture: "+root);return 0;
 }catch(Exception e){Console.WriteLine(e);return 1;}}
}



