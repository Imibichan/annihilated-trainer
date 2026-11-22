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
 readonly bool readOnly;Bridge bridge;bool busy,automatic,closePending;readonly Label connection=new Label(),note=new Label();
 readonly SemaphoreSlim operationGate=new SemaphoreSlim(1,1);
 readonly Button connect=new Button(),refresh=new Button(),heal=new Button(),restore=new Button();
 readonly Label curseBalance=new Label();
 readonly NumericUpDown curseAmount=new NumericUpDown();
 readonly Button applyCurse=new Button();
 bool currencyDirty,loadingCurrency;
 decimal? shownCurrency;
 readonly TextBox history=new TextBox();readonly RolePanel[] roles=new RolePanel[2];
 readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer();bool hotkey;
 [DllImport("user32",SetLastError=true)] static extern bool RegisterHotKey(IntPtr h,int id,uint modifiers,uint vk);
 [DllImport("user32")] static extern bool UnregisterHotKey(IntPtr h,int id);
 public TrainerWindow():this(false){}
 public TrainerWindow(bool inspectOnly,bool offlinePreview=false):this(inspectOnly,offlinePreview,false){}
 public TrainerWindow(bool inspectOnly,bool offlinePreview,bool openGallery){readOnly=inspectOnly;
  Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
  Text="勇者小队全灭了 · 修改器 v1.6 · 原作剧情回放"+(readOnly?"（只读检查）":"");Font=new Font("Microsoft YaHei UI",10);ClientSize=new Size(740,675);MinimumSize=new Size(756,714);MaximumSize=MinimumSize;StartPosition=FormStartPosition.CenterScreen;FormBorderStyle=FormBorderStyle.FixedSingle;MaximizeBox=false;AutoScaleMode=AutoScaleMode.Font;BackColor=Color.FromArgb(246,247,250);
  var title=new Label{Text="勇者小队全灭了",Font=new Font(Font.FontFamily,17,FontStyle.Bold),Location=new Point(22,17),AutoSize=true};Controls.Add(title);
  var guide=new Label{Text="保持修改器打开，额外加成会随升级保留。重启游戏后重新连接。",Location=new Point(24,54),Size=new Size(668,25),ForeColor=Color.DimGray};Controls.Add(guide);
  connect.Text="连接游戏";connect.SetBounds(24,89,140,36);connect.Click+=async delegate{await Connect();};Controls.Add(connect);
  refresh.Text="重新读取";refresh.SetBounds(176,89,125,36);refresh.Click+=async delegate{await Operate("已重新读取角色数据及共享诅咒余额",()=>bridge.ReadTeam(),true,allowReadOnly:true,fillCurrency:true);};Controls.Add(refresh);
  restore.Text="还原正常四维";restore.SetBounds(313,89,174,36);restore.Click+=async delegate{await Operate("已清除所有人物的额外加成，按当前等级还原正常四维",()=>bridge.RestoreNormal(),true);};Controls.Add(restore);
  connection.SetBounds(503,95,190,29);connection.Text="未连接";connection.ForeColor=Color.DimGray;Controls.Add(connection);
  roles[0]=new RolePanel("主角",new Point(24,141));roles[1]=new RolePanel("同伴",new Point(366,141));
  for(int i=0;i<roles.Length;i++){var panel=roles[i];Controls.Add(panel.Group);panel.Apply.Click+=async delegate{
   var values=panel.Values;string id=panel.Id,expected=panel.CharacterKey;if(id==null)return;
   await Operate("已应用"+panel.DisplayName+"的四维",()=>{bridge.Apply(id,expected,values[0],values[1],values[2],values[3]);return bridge.ReadTeam();},true,id);
  };}
  foreach(var panel in roles){panel.ApplySanity.Click+=async delegate {string id=panel.Id,expected=panel.CharacterKey;int value=panel.SanityValue;if(id==null)return;await Operate("已调整 "+panel.DisplayName+" 的 SAN；剧情视觉效果由游戏后续刷新",()=>bridge.ApplySanity(id,expected,value),false,id,true);};}
  var sharedLabel=new Label{Text="共享诅咒货币",AutoSize=true,Location=new Point(24,429)};Controls.Add(sharedLabel);
  curseBalance.Name="curseBalance";curseBalance.Text="尚未读取";curseBalance.SetBounds(128,429,251,29);Controls.Add(curseBalance);
  curseAmount.Name="curseAmount";curseAmount.AccessibleName="目标诅咒余额";curseAmount.Maximum=CurseCurrency.Maximum;curseAmount.SetBounds(384,420,132,32);Controls.Add(curseAmount);
  var currencyRange=new Label{Text="0～9,999,999",Font=new Font(Font.FontFamily,8),ForeColor=Color.DimGray,Location=new Point(384,448),AutoSize=true};Controls.Add(currencyRange);
  curseAmount.ValueChanged+=delegate{if(!loadingCurrency){currencyDirty=true;SetCurrencyEnabled();}};
  curseAmount.TextChanged+=delegate{if(!loadingCurrency)currencyDirty=true;};
  applyCurse.Name="applyCurse";applyCurse.Text="应用诅咒余额";applyCurse.SetBounds(529,420,163,36);
  applyCurse.Click+=async delegate{
   if(!shownCurrency.HasValue||curseAmount.Value>CurseCurrency.Maximum)return;
   decimal expected=shownCurrency.Value;int desired=(int)curseAmount.Value;
   await Operate("已从游戏读回诅咒余额："+desired,()=>{bridge.ApplyCurrency(expected,desired);return bridge.ReadTeam();},false,fillCurrency:true);
  };Controls.Add(applyCurse);
  heal.Text="全队回复最大生命值的 50%   [F8]";heal.SetBounds(24,466,668,45);heal.Font=new Font(Font.FontFamily,12,FontStyle.Bold);heal.BackColor=Color.FromArgb(222,240,229);heal.FlatStyle=FlatStyle.Flat;heal.Click+=async delegate{await Heal();};Controls.Add(heal);
  note.Text="单次回复，不锁血；不超过满血，已倒下的角色不复活。";note.SetBounds(24,516,668,28);note.ForeColor=Color.DimGray;Controls.Add(note);
  history.SetBounds(24,551,668,80);history.Multiline=true;history.ReadOnly=true;history.ScrollBars=ScrollBars.Vertical;history.BackColor=Color.White;history.BorderStyle=BorderStyle.FixedSingle;history.Font=new Font(Font.FontFamily,9);Controls.Add(history);
  timer.Interval=1000;timer.Tick+=async delegate{await AutomaticGrowth();};timer.Start();SetEnabled();Log("就绪。四维按人物保存额外加成；修改前请保留正常存档。");
  var mainPage=new TabPage("角色与战斗");var existing=Controls.Cast<Control>().ToArray();foreach(Control c in existing){Controls.Remove(c);mainPage.Controls.Add(c);}var tabs=new TabControl{Dock=DockStyle.Fill};tabs.TabPages.Add(mainPage);var savesPage=new TabPage("存档（含剧透）");savesPage.Controls.Add(new SavePanel(readOnly));tabs.TabPages.Add(savesPage);Controls.Add(tabs);
  var galleryPage=new TabPage("剧情回放");var gallery=new GalleryPanel(readOnly);galleryPage.Controls.Add(gallery);tabs.TabPages.Add(galleryPage);
  if(openGallery)tabs.SelectedTab=galleryPage;
  tabs.Selected+=async delegate{if(tabs.SelectedTab==galleryPage)await gallery.RefreshState();};
  Shown+=async delegate{if(openGallery)await gallery.RefreshState();else if(!offlinePreview)await Connect();};
  FormClosing+=delegate(object sender,FormClosingEventArgs e){if(gallery.IsApplying){e.Cancel=true;return;}if(SavePanel.IsBusy){e.Cancel=true;Log("存档操作进行中，请完成后关闭。");return;}if(busy||automatic){closePending=true;e.Cancel=true;Log("等待当前操作结束后关闭。");}else{timer.Stop();Disconnect();}};
 }
 async Task Connect(){
  if(busy)return;busy=true;SetEnabled();Log("正在连接当前游戏……");
  await operationGate.WaitAsync();
  try{Bridge previous=bridge;bridge=null;if(previous!=null)await Task.Run(()=>previous.Dispose());
   Bridge next=await Task.Run(()=>new Bridge());bridge=next;var team=await Task.Run(()=>next.ReadTeam());ShowTeam(team,true,fillCurrency:true);
   connection.Text="已连接 · PID "+next.Pid;connection.ForeColor=Color.FromArgb(29,112,68);connect.Text="重新连接";Log(next.CompatibilitySummary);
   Log("资源标识："+(String.IsNullOrEmpty(next.Remote.ContentHash)?"未找到 catalog.hash":next.Remote.ContentHash));
   Log("游戏模块 SHA256："+next.Remote.GameHash);
   if(readOnly)Log("当前为查看模式，可读取角色数据。");
   if(!hotkey){hotkey=RegisterHotKey(Handle,1,0x4000,0x77);if(!hotkey)Log("F8 已被其他程序占用，请使用回血按钮。");}
   Log("连接成功，已读取主角和同伴数据。");
  }catch(Exception ex){Disconnect();Log("连接失败："+ex.Message);}
  finally{operationGate.Release();busy=false;SetEnabled();if(closePending)Close();}
 }
 async Task Heal(){await Operate("全队已按各自生命上限回复 50%",()=>bridge.HealTeam(),false);}
 async Task Operate(string success,Func<Character[]> action,bool fillStats,string editedRole=null,bool sanityEdit=false,bool allowReadOnly=false,bool fillCurrency=false){
  if((readOnly&&!allowReadOnly)||busy||bridge==null)return;busy=true;SetEnabled();await operationGate.WaitAsync();try{
   if(bridge==null)throw new Exception("连接已断开，请重新连接游戏。");
   var team=await Task.Run(action);if(sanityEdit)foreach(var panel in roles)if(panel.Id==editedRole)panel.AcceptSanity();ShowTeam(team,fillStats,editedRole,fillCurrency:fillCurrency);if(success!=null)Log(success);
  }catch(SanityReadbackException ex){
   foreach(var panel in roles)if(panel.Id==ex.Id&&panel.CharacterKey==ex.CharacterKey)panel.ShowRetainedSanity(ex.Actual);
   Log(ex.Message);
  }catch(CurrencyOperationException ex){ShowCurrency(false);Log("诅咒余额操作失败："+ex.Message);}
  catch(Exception ex){Log("操作失败："+ex.Message);Disconnect();}
  finally{operationGate.Release();busy=false;SetEnabled();if(closePending)Close();}
 }
 async Task AutomaticGrowth(){if(readOnly||busy||automatic||closePending||bridge==null)return;automatic=true;await operationGate.WaitAsync();try{
   if(bridge==null)return;if(!bridge.Alive){Disconnect();Log("游戏已退出；下次启动后点击连接游戏。");return;}
   var active=bridge;var result=await Task.Run(()=>active.MaintainGrowth());ShowTeam(result.Team,false,null,true);SetEnabled();if(result.Changed)Log("已在游戏重算后保留人物额外加成。");
  }catch(Exception ex){Log("自动成长维护已停止："+ex.Message);Disconnect();}
  finally{operationGate.Release();automatic=false;if(closePending&&!busy)Close();}
 }
 void ShowTeam(Character[] team,bool fillStats,string editedRole=null,bool autoUpdate=false,bool fillCurrency=false){for(int i=0;i<2;i++){string id=i==0?"player":"partner";var data=team.FirstOrDefault(c=>c.Id==id);roles[i].Show(data,fillStats&&(editedRole==null||editedRole==id),autoUpdate);}ShowCurrency(fillCurrency);}
 void ShowCurrency(bool fill){
  decimal? balance=bridge==null?null:bridge.CurrencyBalance;
  shownCurrency=balance;
  curseBalance.Text=bridge==null?"尚未读取":balance.HasValue?"当前余额："+balance.Value.ToString("0"):"余额不可用（字段缺失或格式异常）";
  if(!balance.HasValue){currencyDirty=false;return;}
  if(!fill&&(currencyDirty||curseAmount.ContainsFocus))return;
  loadingCurrency=true;
  try{curseAmount.Maximum=Math.Max(CurseCurrency.Maximum,balance.Value);curseAmount.Value=balance.Value;currencyDirty=false;}
  finally{loadingCurrency=false;}
 }
 void SetCurrencyEnabled(){
  curseAmount.Enabled=!readOnly&&!busy&&bridge!=null&&bridge.CanBasicWrites&&shownCurrency.HasValue;
  applyCurse.Enabled=curseAmount.Enabled&&curseAmount.Value<=CurseCurrency.Maximum;
 }
 void SetEnabled(){connect.Enabled=!busy;refresh.Enabled=heal.Enabled=restore.Enabled=!busy&&bridge!=null;restore.Enabled=!readOnly&&!busy&&bridge!=null&&bridge.CanGrowth;heal.Enabled=!readOnly&&!busy&&bridge!=null&&bridge.CanBasicWrites;SetCurrencyEnabled();foreach(var p in roles){p.SetEnabled(!readOnly&&!busy&&bridge!=null&&bridge.CanBasicWrites);if(bridge!=null&&!bridge.CanGrowth)p.Apply.Enabled=false;}}
 void Disconnect(){if(hotkey){UnregisterHotKey(Handle,1);hotkey=false;}if(bridge!=null){bridge.Dispose();bridge=null;}connection.Text="未连接";connection.ForeColor=Color.DimGray;connect.Text="连接游戏";ShowCurrency(true);SetEnabled();}
 void Log(string s){string line=DateTime.Now.ToString("HH:mm:ss")+"  "+s;history.AppendText(line+Environment.NewLine);if(history.Lines.Length>60)history.Lines=history.Lines.Skip(history.Lines.Length-50).ToArray();}
 protected override void WndProc(ref Message m){if(m.Msg==0x312&&m.WParam.ToInt32()==1){BeginInvoke(new Action(async delegate{await Heal();}));return;}base.WndProc(ref m);}
 sealed class RolePanel {
  public readonly GroupBox Group=new GroupBox();public readonly Button Apply=new Button(),ApplySanity=new Button();readonly NumericUpDown sanity=new NumericUpDown();readonly Label sanityNote=new Label();bool sanityDirty;readonly Label health=new Label();readonly NumericUpDown[] fields=new NumericUpDown[4];readonly bool[] dirty=new bool[4];bool loading;readonly string title;
  string lastCharacter;public string Id,DisplayName;public int SanityValue{get{return (int)sanity.Value;}}public string CharacterKey{get{return lastCharacter;}}public int[] Values{get{return fields.Select(f=>(int)f.Value).ToArray();}}
  public RolePanel(string name,Point pos){title=name;Group.Text=name;Group.Location=pos;Group.Size=new Size(326,269);Group.BackColor=Color.White;
   health.SetBounds(16,26,290,25);health.Text="尚未读取";Group.Controls.Add(health);
   string[] labels={"力量","灵巧","敏捷","魔力"};for(int i=0;i<4;i++){int x=(i%2)*153+16,y=(i/2)*43+62;var label=new Label{Text=labels[i],Location=new Point(x,y+4),AutoSize=true};Group.Controls.Add(label);
    fields[i]=new NumericUpDown{Minimum=0,Maximum=99999,Location=new Point(x+47,y),Size=new Size(91,28),ThousandsSeparator=false};int index=i;fields[i].ValueChanged+=delegate{if(!loading)dirty[index]=true;};fields[i].TextChanged+=delegate{if(!loading)dirty[index]=true;};Group.Controls.Add(fields[i]);}
   var sanLabel=new Label{Text="SAN",Location=new Point(16,213),AutoSize=true};Group.Controls.Add(sanLabel);sanity.Minimum=-20;sanity.Maximum=100;sanity.SetBounds(63,207,91,28);sanity.ValueChanged+=delegate{if(!loading)sanityDirty=true;};sanity.TextChanged+=delegate{if(!loading)sanityDirty=true;};Group.Controls.Add(sanity);ApplySanity.Text="应用 SAN";ApplySanity.SetBounds(168,206,137,30);Group.Controls.Add(ApplySanity);sanityNote.SetBounds(16,240,290,23);sanityNote.Font=new Font("Microsoft YaHei UI",8);Group.Controls.Add(sanityNote);
   Apply.Text="应用四维";Apply.SetBounds(16,158,290,34);Group.Controls.Add(Apply);
  }
  public void Show(Character c,bool fill,bool autoUpdate){if(c==null){Id=null;Group.Text=title;health.Text="当前没有可读取的角色";return;}bool changedCharacter=Id!=c.Id||lastCharacter!=c.CharacterKey;Id=c.Id;lastCharacter=c.CharacterKey;DisplayName=RoleRules.Label(c.CharacterKey);Group.Text=DisplayName+(String.IsNullOrEmpty(c.Name)||c.Name==c.Id||c.Name==DisplayName?"":" · "+c.Name);health.Text="Lv."+c.Level+"  生命值 "+c.Health+" / "+c.MaxHealth;
   loading=true;try{if(changedCharacter||fill||(!sanityDirty&&!sanity.ContainsFocus)){if(RoleRules.ValidSanity(c.Sanity)){sanity.Value=c.Sanity;sanityDirty=false;}}}finally{loading=false;}sanityNote.Text="当前 SAN："+c.Sanity+((c.Id=="partner"&&(c.CharacterKey=="priest"||c.CharacterKey=="hero"))?"（通常免疫，以游戏读回为准）":"（支持 -20～100）");
   if(fill||autoUpdate){int[] v={c.Str,c.Dex,c.Agi,c.Mag};loading=true;try{for(int i=0;i<4;i++){if(!fill&&!changedCharacter&&(dirty[i]||fields[i].ContainsFocus))continue;if(v[i]<0||v[i]>99999)throw new Exception("当前四维超出支持范围 0～99999。");fields[i].Value=v[i];dirty[i]=false;}}finally{loading=false;}}
  }
  public void AcceptSanity(){sanityDirty=false;}
  public void ShowRetainedSanity(int actual){
   loading=true;
   try{if(RoleRules.ValidSanity(actual))sanity.Value=actual;sanityDirty=false;}
   finally{loading=false;}
   sanityNote.Text="当前 SAN："+actual+"（游戏保留此值）";
  }
  public void SetEnabled(bool enabled){foreach(var f in fields)f.Enabled=enabled&&Id!=null;Apply.Enabled=enabled&&Id!=null;sanity.Enabled=ApplySanity.Enabled=enabled&&Id!=null;}
 }
}
static class Program {
 [STAThread] static void Main(string[] args){bool first;using(var mutex=new Mutex(true,"Local\\Annihilated.PersonalTrainer.v1",out first)){
  if(!first){MessageBox.Show("修改器已经打开，请使用已有窗口。","提示");return;}
  Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new TrainerWindow(Array.IndexOf(args,"--readonly")>=0||Array.IndexOf(args,"--ui-only")>=0,Array.IndexOf(args,"--ui-only")>=0,Array.IndexOf(args,"--gallery")>=0));
 }}
}
