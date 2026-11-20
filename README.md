# 《勇者小队全灭了。》修改器 V1.5

Windows x64 单机修改器，软件和源码免费分享。V1.5 可以从剧情发生前一刻开始回放，保留原作的对白、镜头、音乐和连续 CG。触发剧情所需的战斗动作会自动完成，遇到选项仍由你决定。回放使用独立的临时进度。

**[下载 V1.5 正式包（约 12.8 MB）](https://github.com/Imibichan/annihilated-trainer/releases/tag/v1.5)** · **[观看 B 站实机演示（2 分 31 秒）](https://www.bilibili.com/video/BV15msW6REzc)**

视频介绍本次剧情回放更新，并涵盖隐藏结局改档与四维修改。原百度网盘分享提取码为 `wpaw`。[备用网盘](https://pan.baidu.com/s/1SCNvGLSrBEULi8bZ3gCIfg?pwd=wpaw)

## 打开剧情回放

1. 下载并完整解压 `Annihilated-Trainer-v1.5.zip`，运行「勇者小队全灭了修改器-v1.5.exe」。
2. 打开「剧情回放」页，点击「原作剧情回放」。如果需要手动选择游戏，请选包含 `Annihilated.exe` 的 Steam 安装目录。首次启动会建立约 1.3 GiB 的本地副本，之后可以复用。
3. 选择男女主角，再按路线和章节选一场戏。共收录 **204 个剧情入口**，另有 **15 项独立画稿**。有两套主角形象的事件图和画稿会跟随选择。
4. 点按推进对白，自己选分支。每场回放初始有 999 轮盘货币，多结果的迷宫轮盘可以调整后再接受。看完会回到刚才的目录页，◆ 标出刚看过的项目。

从 V1.4 升级时，如果正式游戏里还保留着旧标题画廊，可以先退出游戏，再到修改器的「剧情回放」页点「关闭旧画廊」。[完整使用说明](docs/使用说明.txt)

## 角色、战斗与存档

- 连接游戏后，可以调整主角和当前同伴的力量、灵巧、敏捷、魔力及 SAN。保持连接可在正常升级时保留额外加成，也可以一键还原当前等级的正常四维。
- 按 F8 为存活队员各回复最大生命值的 50%，最多回到满血。
- 「存档（含剧透）」页提供备份、恢复和隐藏结局资格调整。写入前先退出游戏、确认 Steam 云同步状态并备份存档。后续剧情仍按游戏路线推进。

## 源码与验证

修改器界面及构建脚本位于 `trainer/`，剧情回放代码位于 `replay/`。在 Windows PowerShell 5.1 中，从仓库根目录运行：

```powershell
.\trainer\Build.ps1 -Target Trainer
.\trainer\Test-Gallery.ps1
```

生成的程序位于 `trainer/Trainer.exe`。如需重建完整发布包，先解压 V1.4 正式包，供打包脚本读取基础运行库、资源索引和共用读取模块。以下示例使用 Python 3.11 或以上版本，并假定 V1.4 已解压到仓库旁的 `v1.4` 文件夹。[下载 V1.4 基础包](https://github.com/Imibichan/annihilated-trainer/releases/tag/v1.4)

```powershell
py -3 package_release.py --base ..\v1.4 --docs docs --archive ..\Annihilated-Trainer-v1.5.zip
```

正式包已完成离线回归和资源回读。新增场景的实际播放时序及操作手感尚未逐场实机确认。[验证记录](docs/验证记录.txt) · [完整更新说明（含剧情细节）](docs/更新说明.txt) · [历史版本](https://github.com/Imibichan/annihilated-trainer/releases)

正式包 SHA-256 为 `b20d573403dd229a42ab128b03a1a2fcfb32514e4ad36bf5505df5d597dd9be2`。

本工具为非官方作品。游戏角色、插画、剧情和官方译文归原权利方。
