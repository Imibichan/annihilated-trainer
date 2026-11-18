using System;namespace Trainer{public static class RuntimeRules{
public static bool Schema(bool servicesStatic,string servicesType,int mapOffset,string getReturn,string getArg,string setReturn,string[] setArgs){return servicesStatic&&servicesType=="System.Collections.Generic.List<Naninovel.IEngineService>"&&mapOffset>=16&&mapOffset<4096&&mapOffset%8==0&&getReturn=="System.String"&&getArg=="System.String"&&setReturn=="System.Void"&&setArgs!=null&&setArgs.Length==2&&setArgs[0]=="System.String"&&setArgs[1]=="System.String";}
static bool Identity(string id,string character){return id=="player"?character=="player":id=="partner"&&(character=="hero"||character=="warrior"||character=="mage"||character=="priest");}
public static bool Sanity(string id,string character,int sanity){return Identity(id,character)&&sanity>=-20&&sanity<=100;}
public static bool Health(string id,string character,int hp,int max){return Identity(id,character)&&max>0&&max<=100000000&&hp>=-100000000&&hp<=max;}
}}
