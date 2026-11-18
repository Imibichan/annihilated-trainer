using System;using System.Reflection;using System.Runtime.Serialization;using System.Windows.Forms;using Trainer;
public class ReadOnlyPermissionTests {
 static void Set(object o,string n,object v){o.GetType().GetField(n,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic).SetValue(o,v);}
 static bool Enabled(TrainerWindow w,string n){return ((Button)typeof(TrainerWindow).GetField(n,BindingFlags.Instance|BindingFlags.NonPublic).GetValue(w)).Enabled;}
 static TrainerWindow WindowFor(bool ro,Bridge b){var w=(TrainerWindow)FormatterServices.GetUninitializedObject(typeof(TrainerWindow));Set(w,"readOnly",ro);Set(w,"bridge",b);foreach(string name in new[]{"connect","refresh","heal","restore"})Set(w,name,new Button());var panelType=typeof(TrainerWindow).GetNestedType("RolePanel",BindingFlags.NonPublic);Set(w,"roles",Array.CreateInstance(panelType,0));return w;}
 [STAThread] public static int Main(){try{
  var r=(Remote)FormatterServices.GetUninitializedObject(typeof(Remote));Set(r,"Safety",new SessionSafety());Set(r,"<StaticEnvelopeValidated>k__BackingField",true);
  var b=(Bridge)FormatterServices.GetUninitializedObject(typeof(Bridge));Set(b,"Remote",r);Set(b,"runtimeValidated",true);
  var inspect=WindowFor(true,b);typeof(TrainerWindow).GetMethod("SetEnabled",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(inspect,null);if(Enabled(inspect,"heal")||Enabled(inspect,"restore"))throw new Exception("explicit readonly exposed writes");if(!Enabled(inspect,"refresh"))throw new Exception("explicit readonly lost reads");
  var normal=WindowFor(false,b);typeof(TrainerWindow).GetMethod("SetEnabled",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(normal,null);if(!Enabled(normal,"heal")||!Enabled(normal,"restore"))throw new Exception("validated unknown content is disabled in UI");
  Console.WriteLine("PASS 3 readonly/UI permission assertions");return 0;
 }catch(Exception e){Console.WriteLine("FAIL readonly/UI: "+e);return 1;}}
}
