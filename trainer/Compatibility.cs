using System;using System.IO;using System.Collections.Generic;using System.Text.RegularExpressions;
namespace Trainer {public static class Compatibility {
 public const string OldGame="38F5ADA37FEC235248A61971C06E4ACCF4C95A74B5C74FCCBE32412AB04C26F1", CurrentGame="13B13F97BBE50154B451753351656F99595AE0A542586097F27536F55C24F3C4",OldContent="b9254bd24d0daef581f2186fa1da77c5",CurrentContent="c867cf04b05171a82710f970f4122af7";
 public static readonly string[] RequiredExports={"il2cpp_object_get_class","il2cpp_array_length","il2cpp_field_get_type","il2cpp_field_get_flags","il2cpp_class_get_namespace","il2cpp_class_get_methods","il2cpp_method_get_param_count","il2cpp_method_get_name","il2cpp_domain_get","il2cpp_thread_attach","il2cpp_thread_detach","il2cpp_domain_get_assemblies","il2cpp_assembly_get_image","il2cpp_class_from_name","il2cpp_class_get_fields","il2cpp_field_get_name","il2cpp_field_get_offset","il2cpp_field_static_get_value","il2cpp_class_get_method_from_name","il2cpp_method_get_return_type","il2cpp_method_get_param","il2cpp_type_get_name","il2cpp_string_new","il2cpp_gchandle_new","il2cpp_gchandle_get_target","il2cpp_gchandle_free","il2cpp_runtime_invoke","il2cpp_class_get_name"};
 static bool Eq(string a,string b){return String.Equals(a,b,StringComparison.OrdinalIgnoreCase);}
 public static bool IsKnownBuild(string hash){return Eq(hash,OldGame)||Eq(hash,CurrentGame);}public static bool IsKnownContent(string hash){return Eq(hash,OldContent)||Eq(hash,CurrentContent);}public static bool IsVerifiedPair(string g,string c){return Eq(g,OldGame)&&Eq(c,OldContent);}public static bool IsAnalyzedPair(string g,string c){return Eq(g,CurrentGame)&&Eq(c,CurrentContent);}
 public static void ValidateStatic(byte[] pe,byte[] metadata,string unity,IEnumerable<string> exports,string nativePlayer=null){
  if(pe==null||pe.Length<64||pe[0]!=77||pe[1]!=90)throw new InvalidDataException("模块不是可识别的 Windows PE 文件。");int at=BitConverter.ToInt32(pe,60);
  if(at<64||at>pe.Length-26||BitConverter.ToUInt32(pe,at)!=0x4550||BitConverter.ToUInt16(pe,at+4)!=0x8664||BitConverter.ToUInt16(pe,at+24)!=0x20b)throw new InvalidDataException("仅支持 x64 PE32+ 游戏模块，未执行运行时调用。");
  if(metadata==null||metadata.Length<8||BitConverter.ToUInt32(metadata,0)!=0xfab11baf||BitConverter.ToInt32(metadata,4)!=39)throw new InvalidDataException("IL2CPP 元数据签名或版本不受支持，未执行运行时调用。");
  if(unity==null||!Regex.IsMatch(unity,@"\A[0-9]+\.[0-9]+\.[0-9]+[abfp][0-9]+(?:c[0-9]+)?\z"))throw new InvalidDataException("无法识别 Unity 资源版本标记，未执行运行时调用。");
  // The serialized file labels its producing editor. The native player owns the runtime family.
  string runtime=String.IsNullOrWhiteSpace(nativePlayer)?unity:nativePlayer.Trim();
  if(!Regex.IsMatch(runtime,@"\A6000\.3\.[0-9]+[abfp][0-9]+(?:c[0-9]+)?(?: \([0-9A-Fa-f]{7,40}\))?\z"))throw new InvalidDataException("Unity 原生运行时系列不受支持，未执行运行时调用。");
  var found=new HashSet<string>(exports??new string[0],StringComparer.Ordinal);foreach(string name in RequiredExports)if(!found.Contains(name))throw new InvalidDataException("缺少必要 IL2CPP 接口："+name+"；未执行运行时调用。");
 }
 public static byte[] Prefix(string file,int length){using(var s=File.OpenRead(file)){var b=new byte[Math.Min((long)length,s.Length)];int p=0,n;while(p<b.Length&&(n=s.Read(b,p,b.Length-p))>0)p+=n;return b;}}
 public static string ReadNativePlayerVersion(string directory){
  string player=Path.Combine(directory,"UnityPlayer.dll");
  return File.Exists(player)?System.Diagnostics.FileVersionInfo.GetVersionInfo(player).ProductVersion:null;
 }
 public static string ReadUnityVersion(string file){byte[] b=Prefix(file,256);if(b.Length<49||b[8]!=0||b[9]!=0||b[10]!=0||b[11]!=22)throw new InvalidDataException("未知 Unity 序列化头，拒绝连接。");int end=48;while(end<b.Length&&b[end]!=0)end++;if(end==b.Length)throw new InvalidDataException("Unity 版本标记无效。");return System.Text.Encoding.ASCII.GetString(b,48,end-48);}
}}
