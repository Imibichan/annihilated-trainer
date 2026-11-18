using System;
using System.Reflection;
using System.Runtime.Serialization;
using Trainer;
public class WritePermissionTests {
 static int n;
 static void Check(bool b,string m){if(!b)throw new Exception(m);n++;}
 static void Field(object o,string name,object v){var f=o.GetType().GetField(name,BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public);if(f==null)throw new Exception("missing field "+name);f.SetValue(o,v);}
 static Remote RemoteFor(string content,bool envelope){var r=(Remote)FormatterServices.GetUninitializedObject(typeof(Remote));Field(r,"<ContentHash>k__BackingField",content);Field(r,"<StaticEnvelopeValidated>k__BackingField",envelope);Field(r,"Safety",new SessionSafety());return r;}
 static Bridge BridgeFor(Remote r){var b=(Bridge)FormatterServices.GetUninitializedObject(typeof(Bridge));Field(b,"Remote",r);var ready=typeof(Bridge).GetField("runtimeValidated",BindingFlags.Instance|BindingFlags.NonPublic);if(ready!=null)ready.SetValue(b,true);return b;}
 public static int Main(){try{
  var unknown=RemoteFor("unlisted-future-catalog",true);var b=BridgeFor(unknown);
  Check(!unknown.KnownContent,"unknown resources remain classified as unknown");
  Check(b.CanBasicWrites,"validated unlisted resources must allow attempted health/SAN writes");
  Check(b.CanGrowth,"validated unlisted resources must allow attempted attribute writes");
  Check(!BridgeFor(RemoteFor("",false)).CanBasicWrites,"missing ABI validation must block writes");
  var incomplete=BridgeFor(RemoteFor(Compatibility.CurrentContent,true));Field(incomplete,"runtimeValidated",false);Check(!incomplete.CanBasicWrites,"missing runtime validation blocks known content too");
  var stopped=BridgeFor(RemoteFor(Compatibility.CurrentContent,true));Field(stopped,"disposed",true);Check(!stopped.CanBasicWrites&&!stopped.CanGrowth,"disposed connection blocks all writes");
  unknown.Safety.MarkUncertain();Check(!b.CanBasicWrites&&!b.CanGrowth,"uncertain call blocks all writes");
  Check(BridgeFor(RemoteFor(Compatibility.CurrentContent,true)).CanBasicWrites,"known resources remain writable");
  Check(BridgeFor(RemoteFor("",true)).CanBasicWrites,"missing catalog alone does not block validated runtime");
  Console.WriteLine("PASS "+n+" write permission assertions");return 0;
 }catch(Exception e){Console.WriteLine("FAIL write permission: "+e.Message);return 1;}}
}
