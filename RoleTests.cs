using System;
using System.Reflection;
public static class RoleTests {
 static int count;
 static void Check(bool ok,string name){if(!ok)throw new Exception(name);count++;}
 public static int Main(){try{var a=Assembly.LoadFrom("Trainer.exe");var t=a.GetType("Trainer.RoleRules");Check(t!=null,"RoleRules missing: role labels and SAN validation not implemented");var name=t.GetMethod("Label");Check((string)name.Invoke(null,new object[]{"mage"})=="魔法师","mage label");Check((string)name.Invoke(null,new object[]{"priest"})=="僧侣","priest label");Check((string)name.Invoke(null,new object[]{"hero"})=="勇者","hero label");Check((string)name.Invoke(null,new object[]{"warrior"})=="战士","warrior label");Check((string)name.Invoke(null,new object[]{"unknown"})=="未知角色","unknown label");var valid=t.GetMethod("ValidSanity");Check((bool)valid.Invoke(null,new object[]{-20}),"SAN low boundary");Check((bool)valid.Invoke(null,new object[]{100}),"SAN high boundary");Check(!(bool)valid.Invoke(null,new object[]{-21}),"SAN below boundary");Check(!(bool)valid.Invoke(null,new object[]{101}),"SAN above boundary");Console.WriteLine("PASS "+count+" role/SAN assertions");return 0;}catch(Exception e){Console.WriteLine("FAIL "+e);return 1;}}
}
