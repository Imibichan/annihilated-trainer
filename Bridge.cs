using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Globalization;

namespace Trainer {
// Main-thread dispatch prevents Unity callbacks from being run on a worker thread.
public sealed class Dispatcher : IDisposable {
 readonly Remote r; readonly long page,oldProc,setProc; readonly IntPtr window; readonly uint message; readonly long token;
 bool faulted,installed; public long Output {get{return page+3072;}}
 [DllImport("user32",CharSet=CharSet.Unicode)] static extern uint RegisterWindowMessage(string name);
 [DllImport("user32",SetLastError=true)] static extern IntPtr SendMessageTimeout(IntPtr hwnd,uint msg,IntPtr w,IntPtr l,uint flags,uint timeout,out IntPtr result);
 [DllImport("kernel32")] static extern bool FlushInstructionCache(IntPtr p,IntPtr a,UIntPtr n);
 public Dispatcher(Remote remote){
  r=remote;r.Process.Refresh();window=r.Process.MainWindowHandle;if(window==IntPtr.Zero)throw new Exception("未找到游戏主窗口。");
  message=RegisterWindowMessage("Annihilated.PersonalTrainer.Command.v1");if(message==0)throw new Exception("无法注册窗口消息。");token=DateTime.UtcNow.Ticks;
  setProc=r.SystemFunction("user32.dll","SetWindowLongPtrW");oldProc=r.Call(r.SystemFunction("user32.dll","GetWindowLongPtrW"),window.ToInt64(),-4);
  if(oldProc==0)throw new Exception("无法读取游戏窗口过程。");
  page=r.Alloc(4096,true);var b=new List<byte>();
  // Pass ordinary messages straight through to the original game callback.
  Remote.Imm(b,0x81,0xfa);b.AddRange(BitConverter.GetBytes(message));Remote.Imm(b,0x0f,0x85);int j1=b.Count;b.AddRange(new byte[4]);
  Remote.Imm(b,0x48,0xb8);Remote.U64(b,token);Remote.Imm(b,0x49,0x39,0xc0,0x0f,0x85);int j2=b.Count;b.AddRange(new byte[4]);
  Remote.Imm(b,0x48,0x83,0xec,0x28,0x48,0xb8);Remote.U64(b,page+1024);Remote.Imm(b,0xff,0xd0,0x48,0x83,0xc4,0x28,0x31,0xc0,0xc3);
  int normal=b.Count;Remote.Imm(b,0x48,0xb8);Remote.U64(b,oldProc);Remote.Imm(b,0xff,0xe0);
  var code=b.ToArray();Array.Copy(BitConverter.GetBytes(normal-(j1+4)),0,code,j1,4);Array.Copy(BitConverter.GetBytes(normal-(j2+4)),0,code,j2,4);
  r.Write(page,code);FlushInstructionCache(r.Handle,new IntPtr(page),new UIntPtr(4096));
  long previous=r.Call(setProc,window.ToInt64(),-4,page);if(previous!=oldProc){r.Call(setProc,window.ToInt64(),-4,previous);r.Free(page);throw new Exception("窗口状态发生变化，请重新连接。");}installed=true;
 }
 public long Run(byte[] code){
  if(faulted||!r.Alive)throw new Exception("连接失效，请重新连接。");if(code.Length>1500)throw new Exception("命令过长");
  r.Write(page+1024,code);r.Write(Output,new byte[8]);FlushInstructionCache(r.Handle,new IntPtr(page+1024),new UIntPtr((uint)code.Length));
  IntPtr result;if(SendMessageTimeout(window,message,new IntPtr(token),IntPtr.Zero,3,5000,out result)==IntPtr.Zero){faulted=true;r.MarkUncertain();throw new Exception("游戏未响应，本次操作结果未知。为避免继续使用未完成的调用，请重启游戏后再连接。");}
  return r.Ptr(Output);
 }
 public long Call(long fn,params long[] args){return Run(r.MakeCall(fn,Output,args,false));}
 public long Api(string name,params long[] args){return Call(r.Export("il2cpp_"+name),args);}
 public long RootString(string text){long utf=r.Utf8(text);try{
  var b=new List<byte>();Remote.Imm(b,0x48,0x83,0xec,0x28,0x48,0xb9);Remote.U64(b,utf);Remote.Imm(b,0x48,0xb8);Remote.U64(b,r.Export("il2cpp_string_new"));Remote.Imm(b,0xff,0xd0,0x48,0x89,0xc1,0x31,0xd2,0x48,0xb8);Remote.U64(b,r.Export("il2cpp_gchandle_new"));Remote.Imm(b,0xff,0xd0,0x49,0xbb);Remote.U64(b,Output);Remote.Imm(b,0x49,0x89,0x03,0x48,0x83,0xc4,0x28,0xc3);long h=Run(b.ToArray());if(h==0)throw new Exception("无法创建变量参数");return h;
 }finally{r.Free(utf);}}
 public long Target(long h){return Api("gchandle_get_target",h);}
 public void Unroot(long h){if(h!=0&&!r.Faulted)Api("gchandle_free",h);}
 public void Dispose(){
  if(!installed||!r.Alive||faulted||r.Faulted)return;
  try{long current=r.Call(r.SystemFunction("user32.dll","GetWindowLongPtrW"),window.ToInt64(),-4);if(current==page){r.Call(setProc,window.ToInt64(),-4,oldProc);
   // Retain the small callback page until game exit: other window messages may already be in flight.
   installed=false;}}
  catch{/* Keep callback memory valid until process exit. */}
 }
}
public static class Rules {
 public static int Heal(int hp,int max){if(max<=0||hp<=0)return hp;return (int)Math.Min((long)max,(long)hp+max/2);}
 public static bool ValidStat(int value){return value>=0&&value<=99999;}
}
public sealed class Character {
 public string Id,Name,CharacterKey;public int Str,Dex,Agi,Mag,Health,MaxHealth,Level;
 public int[] NormalStats,Bonuses;
 public int[] GrowthAdds;public bool TrueHero,PoweredMage;public string BattleTarget;
 public int[] Stats{get{return new[]{Str,Dex,Agi,Mag};}}
}
public sealed class StateChangedException : Exception {public StateChangedException():base("人物、等级或存档数据正在变化，已停止本次操作；请稳定后重新读取并应用。部分写入可能已完成。"){} }
public sealed class Bridge : IDisposable {
 public readonly Remote Remote;readonly Dispatcher ui;readonly long engine,managerClass,servicesField,getValue,setValue;readonly int mapOffset;
 readonly Dictionary<string,long> strings=new Dictionary<string,long>();readonly long scratch;bool disposed;
 public int Pid {get{return Remote.Process.Id;}} public bool Alive{get{return !disposed&&Remote.Alive;}}
 public Bridge(){
  Remote=new Remote();try{
   engine=Remote.FindClass("Naninovel","Engine");managerClass=Remote.FindClass("Naninovel","CustomVariableManager");if(engine==0||managerClass==0)throw new Exception("当前游戏版本不兼容。");
   servicesField=Remote.Field(engine,"services");mapOffset=(int)Remote.Api("field_get_offset",Remote.Field(managerClass,"localVariableMap"));
   getValue=Remote.Method(managerClass,"GetVariableValue",1);setValue=Remote.Method(managerClass,"SetVariableValue",2);
   // Check signatures instead of relying on function offsets or a particular build.
   if(Remote.CString(Remote.Api("type_get_name",Remote.Api("method_get_return_type",getValue)))!="System.String")throw new Exception("变量接口类型不兼容。");
   for(int i=0;i<2;i++)if(Remote.CString(Remote.Api("type_get_name",Remote.Api("method_get_param",setValue,i)))!="System.String")throw new Exception("变量写入接口类型不兼容。");
   scratch=Remote.Alloc(128,false);ui=new Dispatcher(Remote);ReadTeam();
  }catch{Dispose();throw;}
 }
 long Service(){
  if(!Alive)throw new Exception("游戏已退出，请重新连接。");
  ui.Api("field_static_get_value",servicesField,scratch);long list=Remote.Ptr(scratch);if(list==0)throw new Exception("游戏尚未初始化。");
  long items=Remote.Ptr(list+16);int count=Remote.Int(list+24);if(count<1||count>500)throw new Exception("游戏服务列表不兼容。");
  for(int i=0;i<count;i++){long obj=Remote.Ptr(items+32+8*i);if(obj==0)continue;if(Remote.Ptr(obj)==managerClass){if(Remote.Ptr(obj+mapOffset)==0)throw new Exception("请先进入存档。");return obj;}}
  throw new Exception("未找到角色变量服务。");
 }
 long Key(string s){long h;if(!strings.TryGetValue(s,out h)){h=ui.RootString(s);strings.Add(s,h);}return h;}
 string Get(long service,string key){
  Remote.Write(scratch+16,BitConverter.GetBytes(ui.Target(Key(key))));Remote.Write(scratch+48,new byte[8]);
  long result=ui.Api("runtime_invoke",getValue,service,scratch+16,scratch+48);CheckException();return Remote.MString(result);
 }
 void CheckException(){long ex=Remote.Ptr(scratch+48);if(ex!=0)throw new Exception("游戏变量接口拒绝本次操作；异常类型："+Remote.CString(ui.Api("class_get_name",Remote.Ptr(ex))));}
 int Number(long svc,string key){int n;if(!int.TryParse(Get(svc,key),NumberStyles.Integer,CultureInfo.InvariantCulture,out n))throw new Exception("变量 "+key+" 不是整数，暂不能修改。");return n;}
 int OptionalNumber(long svc,string key){string value=Get(svc,key);if(String.IsNullOrEmpty(value))return 0;int n;if(!int.TryParse(value,NumberStyles.Integer,CultureInfo.InvariantCulture,out n))throw new Exception("额外加成／成长数据异常："+key);return n;}
 bool Flag(long svc,string key){string value=Get(svc,key);return value=="1"||String.Equals(value,"true",StringComparison.OrdinalIgnoreCase);}
 void Set(long svc,string key,int value){
  if(!Allowed(key))throw new Exception("不允许修改该变量。");long val=ui.RootString(value.ToString(CultureInfo.InvariantCulture));try{
   var args=new byte[16];Array.Copy(BitConverter.GetBytes(ui.Target(Key(key))),0,args,0,8);Array.Copy(BitConverter.GetBytes(ui.Target(val)),0,args,8,8);Remote.Write(scratch+16,args);Remote.Write(scratch+48,new byte[8]);
   ui.Api("runtime_invoke",setValue,svc,scratch+16,scratch+48);CheckException();if(Number(svc,key)!=value)throw new Exception("游戏未接受 "+key+" 的新数值。");
  }finally{ui.Unroot(val);}
 }
 static bool IsBonus(string s){foreach(string c in GrowthRules.Characters)foreach(string k in GrowthRules.Stats)if(s==GrowthRules.BonusKey(c,k))return true;return false;}
 static bool Allowed(string s){if(IsBonus(s))return true;foreach(string p in new[]{"player","partner"})foreach(string k in new[]{"Str","Dex","Agi","Mag","Health"})if(s==p+k)return true;return false;}
 public Character[] ReadTeam(){long svc=Service();var result=new List<Character>();var growth=new int[4];for(int i=0;i<4;i++)growth[i]=OptionalNumber(svc,"player"+GrowthRules.Stats[i]+"Add");bool trueHero=Flag(svc,"xSwitchHeroTrue"),poweredMage=Flag(svc,"xSwitchMageChoiceGetMaryoku");string target=Get(svc,"battleTarget");foreach(string id in new[]{"player","partner"}){
  string name=Get(svc,id+"Name");int max=Number(svc,id+"MaxHealth");if(max<=0){if(id=="player")throw new Exception("请先进入存档，等待角色数据加载。");continue;}
  if(max>100000000)throw new Exception("生命上限超出可识别范围。");
  string character=Get(svc,id+"Character");if(String.IsNullOrEmpty(character))throw new Exception("请先进入存档，等待人物数据加载。");int level=Number(svc,id+"Lv");var bonuses=new int[4];for(int i=0;i<4;i++)bonuses[i]=OptionalNumber(svc,GrowthRules.BonusKey(character,GrowthRules.Stats[i]));
  result.Add(new Character{Id=id,Name=String.IsNullOrEmpty(name)?id:name,CharacterKey=character,Level=level,GrowthAdds=id=="player"?(int[])growth.Clone():new int[4],TrueHero=trueHero,PoweredMage=poweredMage,BattleTarget=target,NormalStats=GrowthRules.Compute(character,level,id=="player"?growth:new int[4],trueHero,poweredMage,target),Bonuses=bonuses,Str=Number(svc,id+"Str"),Dex=Number(svc,id+"Dex"),Agi=Number(svc,id+"Agi"),Mag=Number(svc,id+"Mag"),Health=Number(svc,id+"Health"),MaxHealth=max});
 }return result.ToArray();}
 bool FormulaMatches(long svc,Character c){if(Get(svc,c.Id+"Character")!=c.CharacterKey||Number(svc,c.Id+"Lv")!=c.Level)return false;if(c.Id=="player")for(int i=0;i<4;i++)if(OptionalNumber(svc,"player"+GrowthRules.Stats[i]+"Add")!=c.GrowthAdds[i])return false;if(c.CharacterKey=="hero"&&Flag(svc,"xSwitchHeroTrue")!=c.TrueHero)return false;if(c.CharacterKey=="mage"&&(Flag(svc,"xSwitchMageChoiceGetMaryoku")!=c.PoweredMage||(c.PoweredMage&&Get(svc,"battleTarget")!=c.BattleTarget)))return false;return true;}
 public void Apply(string id,string expectedCharacter,int str,int dex,int agi,int mag){
  if(id!="player"&&id!="partner")throw new Exception("未知角色。");foreach(int v in new[]{str,dex,agi,mag})if(!Rules.ValidStat(v))throw new Exception("四维请输入 0～99999 的整数。");
  Character c=null;foreach(var member in ReadTeam())if(member.Id==id)c=member;if(c==null)throw new Exception("当前角色不可用。");
  if(c.CharacterKey!=expectedCharacter)throw new StateChangedException();
  int[] next={str,dex,agi,mag};var changes=new List<KeyValuePair<string,int>>();for(int i=0;i<4;i++)changes.Add(new KeyValuePair<string,int>(GrowthRules.BonusKey(c.CharacterKey,GrowthRules.Stats[i]),GrowthRules.BonusFor(next[i],c.NormalStats[i])));
  for(int i=0;i<4;i++)changes.Add(new KeyValuePair<string,int>(id+GrowthRules.Stats[i],next[i]));long svc=Service();WriteChanges(changes,()=>FormulaMatches(svc,c));
 }
 void WriteChanges(List<KeyValuePair<string,int>> changes,Func<bool> stillCurrent){long svc=Service();if(!stillCurrent())throw new StateChangedException();var old=new int[changes.Count];for(int i=0;i<changes.Count;i++)old[i]=IsBonus(changes[i].Key)?OptionalNumber(svc,changes[i].Key):Number(svc,changes[i].Key);int done=0;
  try{for(;done<changes.Count;done++)if(changes[done].Value!=old[done]){if(!stillCurrent())throw new StateChangedException();Set(svc,changes[done].Key,changes[done].Value);}}
  catch(Exception original){if(Remote.Faulted)throw new Exception(original.Message+" 属性结果尚未确认，请勿重复操作。",original);if(original is StateChangedException||!stillCurrent())throw new StateChangedException();string restored="已恢复修改前属性与加成。";try{for(int i=0;i<=done&&i<changes.Count;i++)if(changes[i].Value!=old[i]){if(!stillCurrent())throw new StateChangedException();Set(svc,changes[i].Key,old[i]);}}catch{restored="恢复未全部完成，请重新读取数值。";}throw new Exception(original.Message+" "+restored,original);}
 }
 public Character[] RestoreNormal(){var team=ReadTeam();var changes=new List<KeyValuePair<string,int>>();foreach(string c in GrowthRules.Characters)foreach(string stat in GrowthRules.Stats)changes.Add(new KeyValuePair<string,int>(GrowthRules.BonusKey(c,stat),0));foreach(var c in team)for(int i=0;i<4;i++){if(!Rules.ValidStat(c.NormalStats[i]))throw new Exception("当前等级的正常属性超出工具支持范围，未还原。");changes.Add(new KeyValuePair<string,int>(c.Id+GrowthRules.Stats[i],c.NormalStats[i]));}long svc=Service();WriteChanges(changes,()=>{foreach(var c in team)if(!FormulaMatches(svc,c))return false;return true;});return ReadTeam();}
 public GrowthUpdate MaintainGrowth(){var team=ReadTeam();bool changed=false;long svc=0;foreach(var c in team)for(int i=0;i<4;i++){
  int? correction=GrowthRules.Correction(c.Stats[i],c.NormalStats[i],c.Bonuses[i]);if(!correction.HasValue)continue;if(svc==0)svc=Service();
  // A load or companion swap may occur between snapshots. Revalidate identity, level, bonus and raw value before a write.
  string key=GrowthRules.BonusKey(c.CharacterKey,GrowthRules.Stats[i]);if(!FormulaMatches(svc,c)||OptionalNumber(svc,key)!=c.Bonuses[i]||Number(svc,c.Id+GrowthRules.Stats[i])!=c.NormalStats[i])continue;
  Set(svc,c.Id+GrowthRules.Stats[i],correction.Value);changed=true;
 }return new GrowthUpdate{Changed=changed,Team=changed?ReadTeam():team};}
 public Character[] HealTeam(){var team=ReadTeam();long svc=Service();var completed=new List<string>();foreach(var c in team){try{int value=Rules.Heal(c.Health,c.MaxHealth);if(value!=c.Health)Set(svc,c.Id+"Health",value);completed.Add(c.Id=="player"?"主角":"同伴");}
  catch(Exception ex){throw new Exception("回血未全部完成。已确认完成："+(completed.Count==0?"无":String.Join("、",completed))+"。"+(c.Id=="player"?"主角":"同伴")+"本次结果未确认，请先重新读取，勿直接重复回血。 "+ex.Message,ex);}
 }return ReadTeam();}
 public void Dispose(){if(disposed)return;disposed=true;if(ui!=null){try{if(Remote.Alive){foreach(long h in strings.Values)ui.Unroot(h);}}catch{}ui.Dispose();}if(Remote!=null){Remote.Free(scratch);Remote.Dispose();}}
}
}
