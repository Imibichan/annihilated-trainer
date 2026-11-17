# 勇者小队全灭了 修改器 v1.3

Windows x64 独立窗口工具，软件与源码免费分享。需要 .NET Framework 4.x。

## 下载

- [GitHub 最新发行版](https://github.com/Imibichan/annihilated-trainer/releases/latest)：下载 **Annihilated-Trainer-v1.3.zip**，完整解压后运行 EXE。
- [百度网盘](https://pan.baidu.com/s/1SCNvGLSrBEULi8bZ3gCIfg?pwd=wpaw)，提取码 **wpaw**。GitHub 暂时无法访问时可使用网盘。
- [历史版本](https://github.com/Imibichan/annihilated-trainer/releases)。绿色 Code → Download ZIP 下载的是源码，需要自行编译。

## 功能

- 调整主角及当前同伴的力量、灵巧、敏捷、魔力，范围 0～99999。
- 按人物保存额外加成，保持工具打开，升级后的正常成长会继续叠加。例如正常力量 32 改成 100，正常力量升至 34 后得到 102。
- 一键还原当前等级的正常四维。
- 主角和当前同伴独立设置 SAN，范围 -20～100。职业及剧情效果由游戏规则决定。
- F8 或绿色按钮：存活队员各回复最大生命值的 50%，向下取整，不超过满血，不复活。
- 独立的“存档（含剧透）”页：完整备份、恢复，以及隐藏结局资格调整。具体变化会在执行前显示，后续路线仍需在游戏中完成。

## v1.3 更新

保留游戏版本识别，新资源版本可以使用通用模式连接。通过接口、数据结构和角色数据检查后开放修改，不再仅因资源标识未收录而进入只读。连接提示更简洁，窗口和文件属性的版本号统一为 1.3。

游戏更新后，只要接口、数据结构和相关规则保持兼容，即可继续使用。若更新调整了成长公式或结局条件，仍可能需要适配。

## 使用

1. 保留一份正常存档，完整解压发布包。
2. 打开游戏、进入存档，再启动“勇者小队全灭了修改器-v1.3.exe”。
3. 修改数值后点击对应人物的应用按钮。游戏重启后重新连接。
4. 保持工具打开以维护升级后的额外加成。读档或切换人物时，等待数据稳定再操作。

存档备份、恢复及资格调整需要先退出游戏，并处理好 Steam 云同步。工具默认读取当前用户的游戏存档目录，备份保存在 `%LOCALAPPDATA%\AnnihilatedTrainer\Backups`。

“还原正常四维”清除工具记录的额外加成，不倒退等级。角色加成由游戏正常存档保存；存档页则会直接备份或修改选定的磁盘存档。跨保存、退出和重新载入的完整流程尚未单独验证。

## 运行方式与隐私

程序连接本地 `Annihilated` 游戏进程，使用支持的变量接口。没有网络请求、遥测、账号登录、浏览器凭据读取或开机启动逻辑。角色窗口的运行记录不保存为日志文件。

存档功能会在本地写入备份及校验清单；运行接口超时后会在系统临时目录留下通用会话标记，用于提示重启游戏。发布包不含个人存档、私人备份、游戏安装文件或视频制作素材。

本项目并非官方工具，游戏角色及原头像素材属于原权利方。

## 源码构建与测试

在 Windows PowerShell 5.1 中进入仓库根目录后运行：

```powershell
powershell.exe -NoProfile -File .\Build.ps1 -Target Trainer
powershell.exe -NoProfile -File .\Test-InMemory.ps1
powershell.exe -NoProfile -File .\Test-Growth.ps1
powershell.exe -NoProfile -File .\Test-WritePermission.ps1
```

构建生成 `Trainer.exe`。图标、清单和 `VersionInfo.cs` 均为构建文件。离线测试脚本不连接游戏。

本次 120 项离线检查通过；具体覆盖范围见 `验证记录.txt`。通用模式尚未在反馈者的未知游戏版本上完成实机验收。

## 文件校验

发布包 SHA256：`EC340B110C960048591C903DC1BCF375C0458181587D6B4256E5C5F7C83F45EE`

程序 SHA256：`1A821EFC3381613DC0DF6FF6C9476C720B398F9E5B3B2A409F8BAEB92638EF13`
