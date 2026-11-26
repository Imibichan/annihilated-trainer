# 《勇者小队全灭了。》修改器 V1.6.2

Windows x64 单机修改器。支持原作剧情回放、角色四维、SAN、全队回复、共享诅咒货币和存档管理。完整解压发布包后运行「勇者小队全灭了修改器-v1.6.2.exe」。

[下载 V1.6.2 正式包（Windows x64）](https://github.com/Imibichan/annihilated-trainer/releases/download/v1.6.2/Annihilated-Trainer-v1.6.2.zip) · [GitHub 发布说明](https://github.com/Imibichan/annihilated-trainer/releases/tag/v1.6.2)

## 从 V1.5、V1.6 或 V1.6.1 升级

V1.6.2 修复 Windows 路径过长导致回放副本创建失败的问题。遇到过 `FileNotFoundError` 的玩家可直接使用新版重试。修改器会处理旧版复制中断留下的临时副本。

退出旧修改器及回放窗口，在新版的「剧情回放」页点「原作剧情回放」。首次启动会读取当前 Steam 游戏，建立独立副本，迁入可识别的回放偏好，校验后自动清理同一安装的旧游戏副本。回放每次启动都会读取正式游戏的语言选择。选择英语或日语时，中文回放目录会用原作字库补齐缺字，剧情对白使用所选语言。日常游玩的正式存档与回放进度分开保存。

当前 Steam 构建收录 204 个剧情入口、15 项独立画稿。魔法师第四层与僧侣第四层、终章已接入本次原作更新。选好主角和场景即可观看原作演出，剧情选项仍由玩家操作。游戏以后更新时，按实际脚本和资源判断兼容性。[使用说明](docs/使用说明.txt) · [更新说明](docs/更新说明.txt) · [验证记录](docs/验证记录.txt)

## 角色、战斗与存档

- 载入正式游戏进度后连接修改器。主角和同伴可分别调整四维及 SAN；保持连接可在升级时继续保留额外加成。
- 「共享诅咒货币」读取队伍的可花余额。输入 0～9,999,999 后点「应用诅咒余额」，工具会读回确认，保留累计获得量。
- F8 为存活队员各回复最大生命值的 50%，最多回满。
- 「存档（含剧透）」提供完整备份、恢复及隐藏结局资格调整。退出正式游戏并处理好 Steam 云同步后再执行存档写入。

## 从源码构建

WinForms 修改器位于 `trainer/`，使用 Windows PowerShell 5.1 构建。

```powershell
.\trainer\Build.ps1 -Target Trainer
.\trainer\Test-Gallery.ps1
```

完整包需要 Python 3.11 或以上版本，以及已解压的 V1.4 正式包，供构建时读取内嵌运行库和基础资源索引。玩家使用打包好的 V1.6.2 即可。[V1.4 基础包](https://github.com/Imibichan/annihilated-trainer/releases/tag/v1.4)

```powershell
py -3 package_release.py --base ..\v1.4 --docs docs --archive ..\Annihilated-Trainer-v1.6.2.zip
```

本工具为非官方作品。游戏角色、插画、剧情与官方译文归原权利方。过往版本的视频仍可用来了解回放的操作方式。[V1.5 实机演示](https://www.bilibili.com/video/BV15msW6REzc)
