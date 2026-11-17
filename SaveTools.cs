using System;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using System.Runtime.InteropServices;
namespace Trainer {
public sealed class EligibilityInfo {
 public int LoopCount,HeroClears,MageClears,WarriorClears; public string GlobalHash;
 public bool Eligible {get{return LoopCount<=8&&HeroClears==0&&MageClears==0&&WarriorClears==0;}}
 public bool NeedsRepair {get{return LoopCount>7||HeroClears!=0||MageClears!=0||WarriorClears!=0;}}
}
public static class SaveTools {
 const string GlobalName="GlobalSave.nson";
 const string StateKey="Naninovel.CustomVariableManager+GlobalState, Elringus.Naninovel.Runtime, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null";
 static readonly string[] Counters={"G_gameLoopCount","G_gameClearHeroCount","G_gameClearMageCount","G_gameClearWarriorCount"};
 static readonly object Gate=new object();
 const int Limit=32*1024*1024;
  [DllImport("shell32.dll",CharSet=CharSet.Unicode)]
 static extern int SHGetKnownFolderPath(ref Guid folder,uint flags,IntPtr token,out IntPtr path);
 static string LocalLowDirectory(){
  IntPtr pointer=IntPtr.Zero;
  try{
   Guid folder=new Guid("A520A1A4-1780-4FF6-BD18-167343C5AF16");
   if(SHGetKnownFolderPath(ref folder,0,IntPtr.Zero,out pointer)==0){
    string path=Marshal.PtrToStringUni(pointer);
    if(!String.IsNullOrWhiteSpace(path)&&Path.IsPathRooted(path))return path;
   }
  }catch(DllNotFoundException){}catch(EntryPointNotFoundException){}
  finally{if(pointer!=IntPtr.Zero)Marshal.FreeCoTaskMem(pointer);}
  string profile=Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
  if(String.IsNullOrWhiteSpace(profile))throw new IOException("无法确定当前 Windows 用户目录，请手动选择存档目录。");
  return Path.Combine(profile,"AppData","LocalLow");
 }
 public static string DefaultSaveDirectory {get{return Path.Combine(LocalLowDirectory(),"DeathKumiai","Annihilated","NaninovelData","Saves");}}
 public static string DefaultBackupDirectory {get{
  string local=Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
  if(String.IsNullOrWhiteSpace(local))throw new IOException("无法确定当前用户的本地应用数据目录。");
  return Path.Combine(local,"AnnihilatedTrainer","Backups");
 }}
 static JavaScriptSerializer Json(){return new JavaScriptSerializer{MaxJsonLength=Limit,RecursionLimit=100};}
 static void Stopped(){foreach(Process p in Process.GetProcessesByName("Annihilated")){p.Dispose();throw new InvalidOperationException("请先完全退出游戏，再进行存档操作。");}}
 static string Dir(string p,bool exists){
  if(String.IsNullOrWhiteSpace(p))throw new InvalidDataException("存档路径为空。");
  p=Path.GetFullPath(p).TrimEnd(Path.DirectorySeparatorChar);
  if(p.Length<4)throw new InvalidDataException("目录不安全，请选择具体文件夹。");
  if(exists&&!Directory.Exists(p))throw new DirectoryNotFoundException("目录不存在，请先选择已有的存档或备份文件夹："+p);
  for(string q=p;!String.IsNullOrEmpty(q);q=Path.GetDirectoryName(q)){
   if((Directory.Exists(q)||File.Exists(q))&&(File.GetAttributes(q)&FileAttributes.ReparsePoint)!=0)throw new InvalidDataException("不支持链接或重解析点目录。");
  }
  return p;
 }
 static bool Inside(string child,string parent){return child.Equals(parent,StringComparison.OrdinalIgnoreCase)||child.StartsWith(parent+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase);}
 static void Separate(string dir,string root){if(Inside(root,dir)||Inside(dir,root))throw new InvalidDataException("备份目录与存档目录必须相互独立。");}
 static void Name(string n){if(String.IsNullOrEmpty(n)||n!=Path.GetFileName(n)||n.IndexOfAny(Path.GetInvalidFileNameChars())>=0||n=="."||n==".."||n.EndsWith(".")||n.EndsWith(" "))throw new InvalidDataException("备份包含不安全的文件名。");}
 static byte[] Read(string p){if(!File.Exists(p))throw new FileNotFoundException("所需文件不存在，请检查存档或完整备份："+Path.GetFileName(p),p);if((File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0||new FileInfo(p).Length>Limit)throw new InvalidDataException("不支持的存档文件。");return File.ReadAllBytes(p);}
 static string Hash(byte[] b){using(SHA256 s=SHA256.Create())return BitConverter.ToString(s.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
 static Dictionary<string,byte[]> Snapshot(string dir){
  Dir(dir,true); if(Directory.GetDirectories(dir).Length!=0)throw new InvalidDataException("存档含未知子目录，已停止操作。");
  var result=new Dictionary<string,byte[]>(StringComparer.OrdinalIgnoreCase);
  foreach(string f in Directory.GetFiles(dir)){string n=Path.GetFileName(f);Name(n);result.Add(n,Read(f));}
  if(!result.ContainsKey(GlobalName))throw new InvalidDataException("未找到 GlobalSave.nson。");
  return result;
 }
 static void Same(Dictionary<string,byte[]> a,Dictionary<string,byte[]> b){if(a.Count!=b.Count)throw new IOException("存档在操作期间发生变化，请关闭游戏和云同步后重试。");foreach(var p in a)if(!b.ContainsKey(p.Key)||Hash(p.Value)!=Hash(b[p.Key]))throw new IOException("存档在操作期间发生变化，请关闭游戏和云同步后重试。");}
 static Dictionary<string,object> Obj(object o){var d=o as Dictionary<string,object>;if(d==null)throw new InvalidDataException("未知存档结构。");return d;}
 static object Get(Dictionary<string,object> d,string key){object o;if(!d.TryGetValue(key,out o))throw new InvalidDataException("存档字段缺失："+key);return o;}
 static IList List(object o){var a=o as IList;if(a==null)throw new InvalidDataException("未知存档列表格式。");return a;}
 static void Map(Dictionary<string,object> map,out IList keys,out IList values){
  keys=List(Get(map,"keys"));values=List(Get(map,"values"));if(keys.Count!=values.Count)throw new InvalidDataException("存档键值数量不一致。");
  var seen=new HashSet<string>(StringComparer.Ordinal);for(int i=0;i<keys.Count;i++){string k=keys[i] as string;if(k==null||!seen.Add(k)||!(values[i] is string))throw new InvalidDataException("存档含重复键或未知值类型。");}
 }
 sealed class State {public Dictionary<string,object> Outer,Inner;public IList OuterValues,Keys,Values;public int Index;public EligibilityInfo Info;}
 static State Parse(byte[] bytes){
  string text;using(var input=new MemoryStream(bytes))using(var zip=new DeflateStream(input,CompressionMode.Decompress))using(var output=new MemoryStream()){
   var buf=new byte[8192];int n;while((n=zip.Read(buf,0,buf.Length))>0){if(output.Length+n>Limit)throw new InvalidDataException("解压存档过大。");output.Write(buf,0,n);}
   byte[] raw=output.ToArray();int start=raw.Length>=3&&raw[0]==239&&raw[1]==187&&raw[2]==191?3:0;text=new UTF8Encoding(false,true).GetString(raw,start,raw.Length-start);
  }
  var s=new State();s.Outer=Obj(Json().DeserializeObject(text));IList keys,values;Map(Obj(Get(s.Outer,"objectJsonMap")),out keys,out values);
  s.Index=-1;for(int i=0;i<keys.Count;i++)if((string)keys[i]==StateKey)s.Index=i;
  if(s.Index<0)throw new InvalidDataException("不支持的存档版本：未找到已验证的全局状态。");
  s.OuterValues=values;s.Inner=Obj(Json().DeserializeObject((string)values[s.Index]));
  Map(Obj(Get(s.Inner,"GlobalVariableMap")),out s.Keys,out s.Values);
  int[] counts=new int[4];for(int i=0;i<4;i++){int index=s.Keys.IndexOf(Counters[i]);int v;if(index<0||!Int32.TryParse((string)s.Values[index],System.Globalization.NumberStyles.None,System.Globalization.CultureInfo.InvariantCulture,out v)||v<0)throw new InvalidDataException("结局计数缺失或无效："+Counters[i]);counts[i]=v;}
  s.Info=new EligibilityInfo{LoopCount=counts[0],HeroClears=counts[1],MageClears=counts[2],WarriorClears=counts[3],GlobalHash=Hash(bytes)};return s;
 }
 static byte[] Encode(State s){
  s.OuterValues[s.Index]=Json().Serialize(s.Inner);byte[] raw=new UTF8Encoding(true).GetBytes("\uFEFF"+Json().Serialize(s.Outer));
  using(var output=new MemoryStream()){using(var zip=new DeflateStream(output,CompressionMode.Compress,true))zip.Write(raw,0,raw.Length);return output.ToArray();}
 }
 public static EligibilityInfo Inspect(string dir){lock(Gate){Stopped();return Parse(Read(Path.Combine(Dir(dir,true),GlobalName))).Info;}}
 static string SaveSnapshot(string root,Dictionary<string,byte[]> files){
  root=Dir(root,false);Directory.CreateDirectory(root);string backup=Path.Combine(root,DateTime.UtcNow.ToString("yyyyMMdd-HHmmss")+"-"+Guid.NewGuid().ToString("N"));
  string data=Path.Combine(backup,"files");Directory.CreateDirectory(data);var hashes=new Dictionary<string,string>();
  foreach(var p in files){File.WriteAllBytes(Path.Combine(data,p.Key),p.Value);hashes.Add(p.Key,Hash(p.Value));}
  var manifest=new Dictionary<string,object>{{"formatVersion",1},{"createdUtc",DateTime.UtcNow.ToString("o")},{"files",hashes}};
  File.WriteAllText(Path.Combine(backup,"manifest.json"),Json().Serialize(manifest),new UTF8Encoding(false));
  Same(files,LoadSnapshot(backup,root,false));return backup;
 }
 static Dictionary<string,byte[]> LoadSnapshot(string backup,string root,bool validateGlobal){
  root=Dir(root,true);backup=Dir(backup,true);if(!Inside(backup,root)||backup.Equals(root,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("请选择此备份目录中的完整备份。");
  var m=Obj(Json().DeserializeObject(new UTF8Encoding(false,true).GetString(Read(Path.Combine(backup,"manifest.json")))));
  if(!(Get(m,"formatVersion") is int)||(int)m["formatVersion"]!=1)throw new InvalidDataException("不支持的备份版本。");
  var expected=Obj(Get(m,"files"));var files=Snapshot(Path.Combine(backup,"files"));if(files.Count!=expected.Count)throw new InvalidDataException("备份文件清单不匹配。");
  foreach(var p in expected){Name(p.Key);if(!(p.Value is string)||!files.ContainsKey(p.Key)||Hash(files[p.Key])!=(string)p.Value)throw new InvalidDataException("备份完整性验证失败。");}
  if(validateGlobal)Parse(files[GlobalName]);return files;
 }
 public static string Backup(string dir,string root){lock(Gate){Stopped();dir=Dir(dir,true);root=Dir(root,false);Separate(dir,root);var files=Snapshot(dir);Parse(files[GlobalName]);string backup=SaveSnapshot(root,files);Stopped();Same(files,Snapshot(dir));return backup;}}
 static void AtomicWrite(string path,byte[] bytes){
  string temp=path+".trainer-"+Guid.NewGuid().ToString("N")+".tmp";
  try{File.WriteAllBytes(temp,bytes);if(File.Exists(path))File.Replace(temp,path,null);else File.Move(temp,path);}finally{if(File.Exists(temp))File.Delete(temp);}
 }
 public static string RepairEligibility(string dir,string root,string expectedGlobalHash){lock(Gate){
  Stopped();dir=Dir(dir,true);root=Dir(root,false);Separate(dir,root);var before=Snapshot(dir);var state=Parse(before[GlobalName]);
  if(String.IsNullOrEmpty(expectedGlobalHash)||!String.Equals(expectedGlobalHash,state.Info.GlobalHash,StringComparison.OrdinalIgnoreCase))throw new IOException("存档已变化，请重新读取后再修复。");
  if(!state.Info.NeedsRepair)return null;
  state.Values[state.Keys.IndexOf(Counters[0])]=Math.Min(state.Info.LoopCount,7).ToString(System.Globalization.CultureInfo.InvariantCulture);
  for(int i=1;i<4;i++)state.Values[state.Keys.IndexOf(Counters[i])]="0";
  byte[] repaired=Encode(state);if(Parse(repaired).Info.NeedsRepair)throw new InvalidDataException("修复校验失败。");
  string backup=SaveSnapshot(root,before);Stopped();Same(before,Snapshot(dir));
  AtomicWrite(Path.Combine(dir,GlobalName),repaired);if(Hash(Read(Path.Combine(dir,GlobalName)))!=Hash(repaired))throw new IOException("写入验证失败，请使用保护备份恢复："+backup);
  return backup;
 }}
 public static string Restore(string dir,string backup,string root){lock(Gate){
  Stopped();dir=Dir(dir,true);root=Dir(root,true);Separate(dir,root);var restored=LoadSnapshot(backup,root,true);var before=Snapshot(dir);
  string protective=SaveSnapshot(root,before);Stopped();Same(before,Snapshot(dir));
  try{
   foreach(var p in restored)AtomicWrite(Path.Combine(dir,p.Key),p.Value);
   foreach(var p in before)if(!restored.ContainsKey(p.Key))File.Delete(Path.Combine(dir,p.Key));
   Same(restored,Snapshot(dir));
  }catch(Exception ex){
   // A complete protective copy is retained even if the disk becomes unwritable.
   throw new IOException("恢复未完全完成。请勿启动游戏，请从保护备份恢复："+protective,ex);
  }
  return protective;
 }}
}
}



