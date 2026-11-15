using System;
using System.IO;
using System.Text;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using System.ComponentModel;
using System.Security.Cryptography;

namespace Trainer {
public sealed class SessionSafety {
 public bool MayRelease {get;private set;}
 public SessionSafety(){MayRelease=true;}
 public void MarkUncertain(){MayRelease=false;}
}
// Only attaches to Annihilated.exe. No driver, networking, persistence or security settings.
public sealed class Remote : IDisposable {
 public readonly Process Process; public readonly IntPtr Handle; public readonly long GameBase;
 readonly Dictionary<string,long> exports=new Dictionary<string,long>();
 public long Domain,Attach;
 public readonly SessionSafety Safety=new SessionSafety();
 static readonly HashSet<string> uncertainProcesses=new HashSet<string>();
 readonly string identity,uncertainMarker;
 public bool Faulted{get{return !Safety.MayRelease;}}
 public static bool IsSupportedBuild(string hash){return String.Equals(hash,"38F5ADA37FEC235248A61971C06E4ACCF4C95A74B5C74FCCBE32412AB04C26F1",StringComparison.OrdinalIgnoreCase);}
 public static bool IsSupportedContent(string hash){return String.Equals(hash,"b9254bd24d0daef581f2186fa1da77c5",StringComparison.OrdinalIgnoreCase);}
 public void MarkUncertain(){Safety.MarkUncertain();lock(uncertainProcesses)uncertainProcesses.Add(identity);try{File.WriteAllText(uncertainMarker,"Pending runtime call; restart this game process before reconnecting.");}catch{/* The in-process guard remains active. */}}
 [DllImport("kernel32",SetLastError=true)] static extern IntPtr OpenProcess(uint rights,bool inherit,int pid);
 [DllImport("kernel32",SetLastError=true)] static extern bool ReadProcessMemory(IntPtr p,IntPtr a,byte[] b,IntPtr n,out IntPtr done);
 [DllImport("kernel32",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr p,IntPtr a,byte[] b,IntPtr n,out IntPtr done);
 [DllImport("kernel32",SetLastError=true)] static extern IntPtr VirtualAllocEx(IntPtr p,IntPtr a,UIntPtr n,uint type,uint protect);
 [DllImport("kernel32")] static extern bool VirtualFreeEx(IntPtr p,IntPtr a,UIntPtr n,uint type);
 [DllImport("kernel32",SetLastError=true)] static extern IntPtr CreateRemoteThread(IntPtr p,IntPtr attr,UIntPtr stack,IntPtr start,IntPtr arg,uint flags,out uint id);
 [DllImport("kernel32")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
 [DllImport("kernel32")] static extern bool CloseHandle(IntPtr h);
 [DllImport("kernel32")] static extern bool FlushInstructionCache(IntPtr p,IntPtr a,UIntPtr n);
 public Remote() {
  var found=Process.GetProcessesByName("Annihilated");
  if(found.Length!=1)throw new Exception(found.Length==0?"请先启动游戏。":"发现多个游戏进程，请只保留一个。");
  Process=found[0];identity=Process.Id+":"+Process.StartTime.ToUniversalTime().Ticks;
  uncertainMarker=Path.Combine(Path.GetTempPath(),"AnnihilatedTrainer-"+identity.Replace(':','-')+".unsafe");
  lock(uncertainProcesses)if(uncertainProcesses.Contains(identity)||File.Exists(uncertainMarker))throw new Exception("本次游戏会话曾发生调用超时。请重启游戏后再连接，不能直接重连。");
  Handle=OpenProcess(0x43A,false,Process.Id);
  if(Handle==IntPtr.Zero)throw new Win32Exception(Marshal.GetLastWin32Error(),"无法连接游戏进程");
  try {
   foreach(ProcessModule m in Process.Modules)if(m.ModuleName.Equals("GameAssembly.dll",StringComparison.OrdinalIgnoreCase)){
    GameBase=m.BaseAddress.ToInt64();string hash;using(var sha=SHA256.Create())using(var stream=File.OpenRead(m.FileName))hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","");
    if(!IsSupportedBuild(hash))throw new Exception("游戏文件与已验证版本不同，可能已经更新，需要重新适配；未执行修改。");
    string catalog=Path.Combine(Path.GetDirectoryName(m.FileName),"Annihilated_Data","StreamingAssets","aa","catalog.hash");if(!File.Exists(catalog)||!IsSupportedContent(File.ReadAllText(catalog).Trim()))throw new Exception("游戏资源／成长公式版本不同，需要重新适配；未执行修改。");
   }
   if(GameBase==0)throw new Exception("尚未加载 GameAssembly.dll。");
   LoadExports();
  }catch{CloseHandle(Handle);throw;}
 }
 public bool Alive {get{try{return !Process.HasExited;}catch{return false;}}}
 public void Dispose(){CloseHandle(Handle);Process.Dispose();}
 public byte[] Read(long a,int n){if(a<0x10000||n<0||n>16777216)throw new Exception("无效读取范围");var b=new byte[n];IntPtr done;if(!ReadProcessMemory(Handle,new IntPtr(a),b,new IntPtr(n),out done)||done.ToInt64()!=n)throw new Win32Exception(Marshal.GetLastWin32Error(),"读取游戏数据失败");return b;}
 public void Write(long a,byte[] b){IntPtr done;if(!WriteProcessMemory(Handle,new IntPtr(a),b,new IntPtr(b.Length),out done)||done.ToInt64()!=b.Length)throw new Win32Exception(Marshal.GetLastWin32Error(),"写入游戏数据失败");}
 public long Ptr(long a){return BitConverter.ToInt64(Read(a,8),0);}
 public int Int(long a){return BitConverter.ToInt32(Read(a,4),0);}
 public string CString(long a){if(a==0)return "";var b=new List<byte>();for(int i=0;i<2048;i++){byte c=Read(a+i,1)[0];if(c==0)break;b.Add(c);}return Encoding.UTF8.GetString(b.ToArray());}
 public string MString(long a){if(a==0)return "";int n=Int(a+16);if(n<0||n>100000)throw new Exception("无效字符串");return Encoding.Unicode.GetString(Read(a+20,n*2));}
 public long Alloc(int n,bool executable){if(Faulted)throw new Exception("调用结果未知，请重启游戏后再连接。");var p=VirtualAllocEx(Handle,IntPtr.Zero,new UIntPtr((uint)n),0x3000,executable?0x40u:0x04u);if(p==IntPtr.Zero)throw new Win32Exception();return p.ToInt64();}
 public void Free(long a){if(a!=0&&Safety.MayRelease)VirtualFreeEx(Handle,new IntPtr(a),UIntPtr.Zero,0x8000);}
 public long Utf8(string s){byte[] b=Encoding.UTF8.GetBytes(s+"\0");long p=Alloc(b.Length,false);Write(p,b);return p;}
 public long Export(string name){long a;if(!exports.TryGetValue(name,out a))throw new Exception("游戏接口缺失："+name);return a;}
 void LoadExports(){
  int pe=Int(GameBase+0x3c);long nt=GameBase+pe;
  if(Int(GameBase)!=0x00905A4D && (Int(GameBase)&0xffff)!=0x5a4d)throw new Exception("无效模块");
  int rva=Int(nt+0x88);long dir=GameBase+(uint)rva;
  int count=Int(dir+24);long funcs=GameBase+(uint)Int(dir+28),names=GameBase+(uint)Int(dir+32),ords=GameBase+(uint)Int(dir+36);
  if(count<1||count>10000)throw new Exception("导出表不兼容");
  var nb=Read(names,count*4);var ob=Read(ords,count*2);
  for(int i=0;i<count;i++){
   string name=CString(GameBase+BitConverter.ToUInt32(nb,i*4));int ord=BitConverter.ToUInt16(ob,i*2);
   exports[name]=GameBase+(uint)Int(funcs+ord*4);
  }
 }
 public static void Imm(List<byte>b,params byte[] code){b.AddRange(code);}
 public static void U64(List<byte>b,long value){b.AddRange(BitConverter.GetBytes(value));}
 public byte[] MakeCall(long fn,long output,long[] args,bool attach){
  if(args.Length>4)throw new Exception("参数过多");var b=new List<byte>();Imm(b,0x48,0x83,0xec,0x28);
  if(attach&&Attach!=0&&Domain!=0){Imm(b,0x48,0xb9);U64(b,Domain);Imm(b,0x48,0xb8);U64(b,Attach);Imm(b,0xff,0xd0,0x48,0x89,0x44,0x24,0x20);}
  byte[][] regs={new byte[]{0x48,0xb9},new byte[]{0x48,0xba},new byte[]{0x49,0xb8},new byte[]{0x49,0xb9}};
  for(int i=0;i<args.Length;i++){b.AddRange(regs[i]);U64(b,args[i]);}
  Imm(b,0x48,0xb8);U64(b,fn);Imm(b,0xff,0xd0,0x49,0xbb);U64(b,output);Imm(b,0x49,0x89,0x03);
  if(attach&&Attach!=0&&Domain!=0){Imm(b,0x48,0x8b,0x4c,0x24,0x20,0x48,0xb8);U64(b,Export("il2cpp_thread_detach"));Imm(b,0xff,0xd0);}
  Imm(b,0x31,0xc0,0x48,0x83,0xc4,0x28,0xc3);return b.ToArray();
 }
 public long Call(long fn,params long[] args){
  long p=Alloc(4096,true);IntPtr thread=IntPtr.Zero;bool finished=true;
  try{Write(p,MakeCall(fn,p+2048,args,true));FlushInstructionCache(Handle,new IntPtr(p),new UIntPtr(4096));uint id;
   thread=CreateRemoteThread(Handle,IntPtr.Zero,UIntPtr.Zero,new IntPtr(p),IntPtr.Zero,0,out id);
   if(thread==IntPtr.Zero)throw new Win32Exception(Marshal.GetLastWin32Error(),"游戏拒绝执行接口调用");
   finished=WaitForSingleObject(thread,5000)==0;if(!finished){MarkUncertain();throw new Exception("游戏接口调用超时，结果未知。请重启游戏后再连接。");}return Ptr(p+2048);
  }finally{if(thread!=IntPtr.Zero)CloseHandle(thread);if(finished)Free(p);}
 }
 public long Api(string name,params long[] args){return Call(Export("il2cpp_"+name),args);}
 public long Field(long klass,string name){long iter=Alloc(8,false);try{for(;;){long f=Api("class_get_fields",klass,iter);if(f==0)break;if(CString(Api("field_get_name",f))==name)return f;}}finally{Free(iter);}throw new Exception("游戏字段不兼容："+name);}
 public long Method(long klass,string name,int count){long np=Utf8(name);try{long m=Api("class_get_method_from_name",klass,np,count);if(m==0)throw new Exception("游戏方法不兼容："+name);return m;}finally{Free(np);}}
 [DllImport("kernel32",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandle(string module);
 [DllImport("kernel32",CharSet=CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr module,string name);
 public long SystemFunction(string module,string name){long local=GetModuleHandle(module).ToInt64();long fn=GetProcAddress(new IntPtr(local),name).ToInt64();if(local==0||fn==0)throw new Exception("缺少系统函数 "+name);foreach(ProcessModule m in Process.Modules)if(m.ModuleName.Equals(module,StringComparison.OrdinalIgnoreCase))return m.BaseAddress.ToInt64()+fn-local;throw new Exception("游戏尚未加载 "+module);}
 public long FindClass(string ns,string name){
  if(Domain==0){Domain=Api("domain_get");Attach=Export("il2cpp_thread_attach");}
  long count=Alloc(8,false),np=Utf8(ns),cp=Utf8(name);
  try{long list=Api("domain_get_assemblies",Domain,count);long n=Ptr(count);if(n<1||n>1000)throw new Exception("无效程序集数量");
   for(int i=0;i<n;i++){long img=Api("assembly_get_image",Ptr(list+8*i));long c=Api("class_from_name",img,np,cp);if(c!=0)return c;}
  }finally{Free(count);Free(np);Free(cp);}return 0;
 }
 public void Describe(long klass,Action<string> log){
  log("CLASS "+CString(Api("class_get_namespace",klass))+"."+CString(Api("class_get_name",klass))+" @ "+klass.ToString("X"));
  long iter=Alloc(8,false);try{for(;;){long f=Api("class_get_fields",klass,iter);if(f==0)break;log(" FIELD "+CString(Api("field_get_name",f))+" offset="+Api("field_get_offset",f)+" flags="+Api("field_get_flags",f).ToString("X")+" type="+CString(Api("type_get_name",Api("field_get_type",f))));}
   Write(iter,new byte[8]);for(;;){long m=Api("class_get_methods",klass,iter);if(m==0)break;int n=(int)Api("method_get_param_count",m);string s=" METHOD "+CString(Api("method_get_name",m))+"(";for(int j=0;j<n;j++)s+=CString(Api("type_get_name",Api("method_get_param",m,j)))+",";s+=") -> "+CString(Api("type_get_name",Api("method_get_return_type",m)));log(s);}
  }finally{Free(iter);}
 }
}
}
