using System;
using System.IO;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using Trainer;
public sealed class SavePanel : UserControl {
 public static bool IsBusy;
 readonly TextBox directory=new TextBox(),status=new TextBox();
 readonly Button inspect=new Button(),backup=new Button(),repair=new Button(),restore=new Button(),choose=new Button();
 readonly Panel body=new Panel(); readonly Label eligibility=new Label(); EligibilityInfo current;
 string BackupRoot {get{return SaveTools.DefaultBackupDirectory;}}
 public SavePanel(bool readOnly=false){Dock=DockStyle.Fill;BackColor=Color.FromArgb(246,247,250);Font=new Font("Microsoft YaHei UI",9);
  Controls.Add(new Label{Text="建议一周目先正常游玩。下方可直接备份/恢复存档；路线攻略默认折叠。\n资格调整不等于解锁结局，也不会修复已经选错的路线分支。",Location=new Point(20,14),Size=new Size(680,44),ForeColor=Color.DarkRed});
  body.SetBounds(16,64,700,558);Controls.Add(body);
  body.Controls.Add(new Label{Text="存档目录",Location=new Point(6,3),AutoSize=true});directory.Name="saveDirectory";directory.Text=SaveTools.DefaultSaveDirectory;directory.SetBounds(6,26,577,27);body.Controls.Add(directory);choose.Text="浏览";choose.SetBounds(590,24,95,30);body.Controls.Add(choose);choose.Click+=delegate{using(var d=new FolderBrowserDialog()){d.Description="选择包含 GlobalSave.nson 的游戏存档目录";if(Directory.Exists(directory.Text))d.SelectedPath=directory.Text;if(d.ShowDialog()==DialogResult.OK){directory.Text=d.SelectedPath;current=null;eligibility.Text="目录已变化，请重新读取。";}}};directory.TextChanged+=delegate{current=null;eligibility.Text="目录已变化，请重新读取。";};
  var toggle=new CheckBox{Name="walkthroughToggle",Text="展开隐藏结局攻略（剧透，点击才显示）",Location=new Point(6,66),Size=new Size(679,27)};body.Controls.Add(toggle);
  var walkthrough=new Panel{Name="walkthroughPanel",Location=new Point(6,98),Size=new Size(679,177),Visible=false};body.Controls.Add(walkthrough);
  var help=new TextBox{Name="walkthroughText",Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Location=new Point(0,0),Size=new Size(679,146),Text=HiddenRouteGuide.Text};walkthrough.Controls.Add(help);
  var source=new LinkLabel{Text="玩家攻略来源（辅助参考）",Location=new Point(0,151),Size=new Size(240,23)};source.LinkClicked+=delegate{System.Diagnostics.Process.Start("https://steamcommunity.com/sharedfiles/filedetails/?id=3838689657");};walkthrough.Controls.Add(source);
  var source2=new LinkLabel{Text="依存度攻略（辅助参考）",Location=new Point(280,151),Size=new Size(280,23)};source2.LinkClicked+=delegate{System.Diagnostics.Process.Start("https://steamcommunity.com/sharedfiles/filedetails/?id=3838721286");};walkthrough.Controls.Add(source2);
  eligibility.Text="尚未读取。读取不会修改存档。";body.Controls.Add(eligibility);
  inspect.Name="saveInspect";backup.Name="saveBackup";repair.Name="saveRepair";restore.Name="saveRestore";inspect.Text="读取资格";backup.Text="完整备份";repair.Text="恢复隐藏结局资格";restore.Text="恢复备份";Button[] bs={inspect,backup,repair,restore};int[] widths={115,115,225,160};foreach(var b in bs)body.Controls.Add(b);
  var safety=new Label{Text="写入/恢复前退出游戏，并暂停或妥善处理 Steam 云同步。\n每次调整前完整备份；恢复前另存当前状态。恢复会回退整个存档目录。",ForeColor=Color.DarkRed};body.Controls.Add(safety);
  status.Multiline=true;status.ReadOnly=true;status.ScrollBars=ScrollBars.Vertical;body.Controls.Add(status);
  Action layout=delegate{int y=toggle.Checked?285:103;walkthrough.Visible=toggle.Checked;toggle.Text=toggle.Checked?"收起隐藏结局攻略（剧透）":"展开隐藏结局攻略（剧透，点击才显示）";eligibility.SetBounds(6,y,679,45);int x=6;for(int i=0;i<bs.Length;i++){bs[i].SetBounds(x,y+51,widths[i],34);x+=widths[i]+12;}safety.SetBounds(6,y+96,679,46);status.SetBounds(6,y+150,679,toggle.Checked?110:210);};toggle.CheckedChanged+=delegate{layout();};layout();
  inspect.Click+=async delegate{string dir=directory.Text;await Run(()=>{current=SaveTools.Inspect(dir);return Summary(current);},true);};
  backup.Click+=async delegate{string dir=directory.Text;await Run(()=>"完整备份已验证："+SaveTools.Backup(dir,BackupRoot),false);};
  repair.Click+=async delegate{if(current==null){MessageBox.Show("请先读取资格。","提示");return;}if(!current.NeedsRepair){MessageBox.Show("计数已不高于初始值7，且三项通关计数为0，无需修改。后续路线仍须在游戏内完成。","提示");return;}if(MessageBox.Show("将调整：轮回 "+current.LoopCount+" → "+Math.Min(current.LoopCount,7)+"；勇者 "+current.HeroClears+" → 0；魔法师 "+current.MageClears+" → 0；战士 "+current.WarriorClears+" → 0。\n初始值7，资格门槛≤8。先退出游戏并处理 Steam 云同步。\n先完整备份并校验到："+BackupRoot+"\n其余全局值保留。是否继续？","恢复隐藏结局资格",MessageBoxButtons.YesNo,MessageBoxIcon.Warning)!=DialogResult.Yes)return;string dir=directory.Text,hash=current.GlobalHash;await Run(()=>{string path=SaveTools.RepairEligibility(dir,BackupRoot,hash);current=SaveTools.Inspect(dir);return "资格已调整；操作前备份："+path+Environment.NewLine+Summary(current);},true);};
  backup.Enabled=repair.Enabled=restore.Enabled=!readOnly;
  restore.Click+=async delegate{using(var d=new FolderBrowserDialog()){d.Description="选择此工具创建且包含校验清单的备份文件夹";if(Directory.Exists(BackupRoot))d.SelectedPath=BackupRoot;if(d.ShowDialog()!=DialogResult.OK)return;if(MessageBox.Show("将把整个存档目录恢复为所选备份，之后新增的进度也会回退。\n程序会先保护性备份当前状态。请确认已退出游戏并处理好 Steam 云同步。是否继续？","恢复完整备份",MessageBoxButtons.YesNo,MessageBoxIcon.Warning)!=DialogResult.Yes)return;string dir=directory.Text,selected=d.SelectedPath;await Run(()=>{string path=SaveTools.Restore(dir,selected,BackupRoot);current=null;return "恢复完成；恢复前状态已保存在："+path+"。请重新读取资格。";},false);}};
 }
 string Summary(EligibilityInfo v){return "轮回："+v.LoopCount+"；勇者通关："+v.HeroClears+"；魔法师通关："+v.MageClears+"；战士通关："+v.WarriorClears+Environment.NewLine+(v.Eligible?"前置计数满足（不代表已解锁结局）":"前置计数尚不满足");}
 async Task Run(Func<string> operation,bool update){if(IsBusy)return;IsBusy=true;body.Enabled=false;try{string result=await Task.Run(operation);status.AppendText(DateTime.Now.ToString("HH:mm:ss")+" "+result+Environment.NewLine);if(update&&current!=null)eligibility.Text=Summary(current);else if(current==null)eligibility.Text="请重新读取资格。";}catch(Exception e){current=null;eligibility.Text="操作未完成，请重新读取。";status.AppendText("未完成："+e.Message+Environment.NewLine);}finally{body.Enabled=true;IsBusy=false;}}
}
