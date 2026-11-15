using System;
using System.IO;
using System.Drawing;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using Trainer;

public sealed class TrainerWindow : Form {
 Bridge bridge;bool busy,automatic,closePending;readonly Label connection=new Label(),note=new Label();
 readonly SemaphoreSlim operationGate=new SemaphoreSlim(1,1);
 readonly Button connect=new Button(),refresh=new Button(),heal=new Button(),restore=new Button();
 readonly TextBox history=new TextBox();readonly RolePanel[] roles=new RolePanel[2];
 readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer();bool hotkey;
 [DllImport("user32",SetLastError=true)] static extern bool RegisterHotKey(IntPtr h,int id,uint modifiers,uint vk);
 [DllImport("user32")] static extern bool UnregisterHotKey(IntPtr h,int id);
 public TrainerWindow(){
  Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
  Text="勇者小队全灭了 · 自用修改器 1.1";Font=new Font("Microsoft YaHei UI",10);ClientSize=new Size(716,540);MinimumSize=new Size(732,579);MaximumSize=MinimumSize;StartPosition=FormStartPosition.CenterScreen;FormBorderStyle=FormBorderStyle.FixedSingle;MaximizeBox=false;AutoScaleMode=AutoScaleMode.Font;BackColor=Color.FromArgb(246,247,250);
  var title=new Label{Text="勇者小队全灭了",Font=new Font(Font.FontFamily,17,FontStyle.Bold),Location=new Point(22,17),AutoSize=true};Controls.Add(title);
  var guide=new Label{Text="保持修改器打开，额外加成会随升级保留。重启游戏后重新连接。",Location=new Point(24,54),Size=new Size(668,25),ForeColor=Color.DimGray};Controls.Add(guide);
  connect.Text="连接游戏";connect.SetBounds(24,89,140,36);connect.Click+=async delegate{await Connect();};Controls.Add(connect);
  refresh.Text="重新读取";refresh.SetBounds(176,89,125,36);refresh.Click+=async delegate{await Operate("已重新读取角色数据",()=>bridge.ReadTeam(),true);};Controls.Add(refresh);
  restore.Text="还原正常四维";restore.SetBounds(313,89,174,36);restore.Click+=async delegate{await Operate("已清除所有人物的额外加成，按当前等级还原正常四维",()=>bridge.RestoreNormal(),true);};Controls.Add(restore);
  connection.SetBounds(503,95,190,29);connection.Text="未连接";connection.ForeColor=Color.DimGray;Controls.Add(connection);
  roles[0]=new RolePanel("主角",new Point(24,141));roles[1]=new RolePanel("同伴",new Point(366,141));
  for(int i=0;i<roles.Length;i++){var panel=roles[i];Controls.Add(panel.Group);panel.Apply.Click+=async delegate{
   var values=panel.Values;string id=panel.Id,expected=panel.CharacterKey;if(id==null)return;
   await Operate("已应用"+panel.DisplayName+"的四维",()=>{bridge.Apply(id,expected,values[0],values[1],values[2],values[3]);return bridge.ReadTeam();},true,id);
  };}
  heal.Text="全队回复最大生命值的 50%   [F8]";heal.SetBounds(24,365,668,47);heal.Font=new Font(Font.FontFamily,12,FontStyle.Bold);heal.BackColor=Color.FromArgb(222,240,229);heal.FlatStyle=FlatStyle.Flat;heal.Click+=async delegate{await Heal();};Controls.Add(heal);
  note.Text="单次回复，不锁血；不超过满血，已倒下的角色不复活。";note.SetBounds(24,420,668,25);note.ForeColor=Color.DimGray;Controls.Add(note);
  history.SetBounds(24,450,668,69);history.Multiline=true;history.ReadOnly=true;history.ScrollBars=ScrollBars.Vertical;history.BackColor=Color.White;history.BorderStyle=BorderStyle.FixedSingle;history.Font=new Font(Font.FontFamily,9);Controls.Add(history);
  timer.Interval=1000;timer.Tick+=async delegate{await AutomaticGrowth();};timer.Start();SetEnabled();Log("就绪。四维按人物保存额外加成；修改前请保留正常存档。");
  Shown+=async delegate{await Connect();};
  FormClosing+=delegate(object sender,FormClosingEventArgs e){if(busy||automatic){closePending=true;e.Cancel=true;Log("等待当前操作结束后关闭。");}else{timer.Stop();Disconnect();}};
 }
 async Task Connect(){
  if(busy)return;busy=true;SetEnabled();Log("正在连接当前游戏……");
  await operationGate.WaitAsync();
  try{Bridge previous=bridge;bridge=null;if(previous!=null)await Task.Run(()=>previous.Dispose());
   Bridge next=await Task.Run(()=>new Bridge());bridge=next;var team=await Task.Run(()=>next.ReadTeam());ShowTeam(team,true);
   connection.Text="已连接 · PID "+next.Pid;connection.ForeColor=Color.FromArgb(29,112,68);connect.Text="重新连接";
   if(!hotkey){hotkey=RegisterHotKey(Handle,1,0x4000,0x77);if(!hotkey)Log("F8 已被其他程序占用，请使用回血按钮。");}
   Log("连接成功，已读取主角和同伴数据。");
  }catch(Exception ex){Disconnect();Log("连接失败："+ex.Message);}
  finally{operationGate.Release();busy=false;SetEnabled();if(closePending)Close();}
 }
 async Task Heal(){await Operate("全队已按各自生命上限回复 50%",()=>bridge.HealTeam(),false);}
 async Task Operate(string success,Func<Character[]> action,bool fillStats,string editedRole=null){
  if(busy||bridge==null)return;busy=true;SetEnabled();await operationGate.WaitAsync();try{
   if(bridge==null)throw new Exception("连接已断开，请重新连接游戏。");
   var team=await Task.Run(action);ShowTeam(team,fillStats,editedRole);if(success!=null)Log(success);
  }catch(Exception ex){Log("操作失败："+ex.Message);Disconnect();}
  finally{operationGate.Release();busy=false;SetEnabled();if(closePending)Close();}
 }
 async Task AutomaticGrowth(){if(busy||automatic||closePending||bridge==null)return;automatic=true;await operationGate.WaitAsync();try{
   if(bridge==null)return;if(!bridge.Alive){Disconnect();Log("游戏已退出；下次启动后点击连接游戏。");return;}
   var active=bridge;var result=await Task.Run(()=>active.MaintainGrowth());ShowTeam(result.Team,false,null,true);SetEnabled();if(result.Changed)Log("已在游戏重算后保留人物额外加成。");
  }catch(Exception ex){Log("自动成长维护已停止："+ex.Message);Disconnect();}
  finally{operationGate.Release();automatic=false;if(closePending&&!busy)Close();}
 }
 void ShowTeam(Character[] team,bool fillStats,string editedRole=null,bool autoUpdate=false){for(int i=0;i<2;i++){string id=i==0?"player":"partner";var data=team.FirstOrDefault(c=>c.Id==id);roles[i].Show(data,fillStats&&(editedRole==null||editedRole==id),autoUpdate);}}
 void SetEnabled(){connect.Enabled=!busy;refresh.Enabled=heal.Enabled=restore.Enabled=!busy&&bridge!=null;foreach(var p in roles)p.SetEnabled(!busy&&bridge!=null);}
 void Disconnect(){if(hotkey){UnregisterHotKey(Handle,1);hotkey=false;}if(bridge!=null){bridge.Dispose();bridge=null;}connection.Text="未连接";connection.ForeColor=Color.DimGray;connect.Text="连接游戏";SetEnabled();}
 void Log(string s){string line=DateTime.Now.ToString("HH:mm:ss")+"  "+s;history.AppendText(line+Environment.NewLine);if(history.Lines.Length>60)history.Lines=history.Lines.Skip(history.Lines.Length-50).ToArray();}
 protected override void WndProc(ref Message m){if(m.Msg==0x312&&m.WParam.ToInt32()==1){BeginInvoke(new Action(async delegate{await Heal();}));return;}base.WndProc(ref m);}
 sealed class RolePanel {
  public readonly GroupBox Group=new GroupBox();public readonly Button Apply=new Button();readonly Label health=new Label();readonly NumericUpDown[] fields=new NumericUpDown[4];readonly bool[] dirty=new bool[4];bool loading;readonly string title;
  string lastCharacter;public string Id,DisplayName;public string CharacterKey{get{return lastCharacter;}}public int[] Values{get{return fields.Select(f=>(int)f.Value).ToArray();}}
  public RolePanel(string name,Point pos){title=name;Group.Text=name;Group.Location=pos;Group.Size=new Size(326,207);Group.BackColor=Color.White;
   health.SetBounds(16,26,290,25);health.Text="尚未读取";Group.Controls.Add(health);
   string[] labels={"力量","灵巧","敏捷","魔力"};for(int i=0;i<4;i++){int x=(i%2)*153+16,y=(i/2)*43+62;var label=new Label{Text=labels[i],Location=new Point(x,y+4),AutoSize=true};Group.Controls.Add(label);
    fields[i]=new NumericUpDown{Minimum=0,Maximum=99999,Location=new Point(x+47,y),Size=new Size(91,28),ThousandsSeparator=false};int index=i;fields[i].ValueChanged+=delegate{if(!loading)dirty[index]=true;};fields[i].TextChanged+=delegate{if(!loading)dirty[index]=true;};Group.Controls.Add(fields[i]);}
   Apply.Text="应用四维";Apply.SetBounds(16,158,290,34);Group.Controls.Add(Apply);
  }
  public void Show(Character c,bool fill,bool autoUpdate){if(c==null){Id=null;Group.Text=title;health.Text="当前没有可读取的角色";return;}bool changedCharacter=Id!=c.Id||lastCharacter!=c.CharacterKey;Id=c.Id;lastCharacter=c.CharacterKey;DisplayName=c.Name==c.Id?title:c.Name;Group.Text=title+" · "+DisplayName;health.Text="Lv."+c.Level+"  生命值 "+c.Health+" / "+c.MaxHealth;
   if(fill||autoUpdate){int[] v={c.Str,c.Dex,c.Agi,c.Mag};loading=true;try{for(int i=0;i<4;i++){if(!fill&&!changedCharacter&&(dirty[i]||fields[i].ContainsFocus))continue;if(v[i]<0||v[i]>99999)throw new Exception("当前四维超出支持范围 0～99999。");fields[i].Value=v[i];dirty[i]=false;}}finally{loading=false;}}
  }
  public void SetEnabled(bool enabled){foreach(var f in fields)f.Enabled=enabled&&Id!=null;Apply.Enabled=enabled&&Id!=null;}
 }
}
static class Program {
 [STAThread] static void Main(){bool first;using(var mutex=new Mutex(true,"Local\\Annihilated.PersonalTrainer.v1",out first)){
  if(!first){MessageBox.Show("修改器已经打开，请使用已有窗口。","提示");return;}
  Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new TrainerWindow());
 }}
}
