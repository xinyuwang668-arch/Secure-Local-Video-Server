# Secure Local Video Server

一个用于将本地视频临时分享给其他用户进行在线播放的个人开源工具。

本软件适合朋友之间进行临时视频分享。用户可以选择本地视频，并通过网络生成访问地址，使其他用户能够使用浏览器访问并在线播放。

> **注意：本软件主要用于临时在线播放分享，不保证视频绝对无法被保存、缓存、复制或通过其他方式获取。请勿将本软件用于分享违法、侵权或未经授权的内容。**

---

## 功能

* 本地视频在线播放
* 临时网络分享
* 浏览器访问
* 支持文件拖拽
* 分享链接生成
* 可配合 Cloudflare Tunnel 使用
* Windows 图形化操作界面
* 无需每次通过命令行启动

---

## 软件界面

软件启动后可以通过图形化界面进行相关操作。

用户无需手动输入复杂的命令即可启动视频服务器以及进行视频分享。

---

## 使用方法

### 1. 启动软件

运行：

```text
SecureLocalVideoServer.exe
```

启动软件后，根据界面提示选择需要分享的视频。

### 2. 选择视频

可以通过文件选择功能选择本地视频。

部分操作支持直接将视频文件拖拽到软件指定区域。

### 3. 开启分享

启动视频服务器后，软件会根据当前配置提供视频访问地址。

如果使用 Cloudflare Tunnel，软件可以通过 Cloudflare 提供的网络连接方式生成可以从外部访问的地址。

### 4. 分享链接

将生成的访问地址发送给需要观看视频的朋友即可。

请注意：

**获得链接的人可能能够访问对应的视频内容。**

因此，请不要将私人视频或敏感内容的链接公开发布。

---

## Cloudflare Tunnel

本软件可以配合 Cloudflare Tunnel / `cloudflared` 使用。

`cloudflared` 是 Cloudflare 提供的官方程序，本项目本身并不包含 Cloudflare 的服务。

如果需要使用相关功能，请从 Cloudflare 官方渠道获取对应版本的 `cloudflared`。

请遵守 Cloudflare 的服务条款以及相关法律法规。

---

## 下载

正式版本请前往 GitHub 的 **Releases** 页面获取。

推荐普通用户下载 Release 中提供的：

```text
SecureLocalVideoServer_Setup.exe
```

源码用户可以直接下载本项目源代码。

---

## 系统要求

目前主要针对：

* Windows 10
* Windows 11
* x64

建议使用较新的 Windows 系统和现代浏览器。

---

## 开发环境

本项目主要使用：

* Python
* Tkinter
* PyInstaller
* Cloudflare Tunnel / cloudflared

具体依赖请参阅：

```text
requirements.txt
```

---

## 从源码运行

安装 Python 后，在项目目录运行：

```bash
pip install -r requirements.txt
```

然后运行：

```bash
python server_gui_v2.py
```

---

## 从源码打包

本项目使用 PyInstaller 打包。

示例：

```bash
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "SecureLocalVideoServer" --add-binary "cloudflared.exe;." server_gui_v2.py
```

生成的文件通常位于：

```text
dist\SecureLocalVideoServer\
```

---

## 项目结构

```text
SecureLocalVideoServer/
│
├─ server_gui_v2.py
├─ README.md
├─ LICENSE
├─ requirements.txt
├─ .gitignore
├─ 用户须知.md
│
├─ assets/
│   └─ ...
│
└─ releases/
    └─ ...
```

---

## 用户须知与免责声明

使用本软件即表示用户理解并接受相关使用风险。

本软件为个人开发的开源软件。

用户使用本软件向他人分享视频或其他内容时，应自行确认相关内容具有合法的使用权、传播权或其他必要授权。

因用户自身行为、违规使用、分享非法或未经授权内容、第三方网络服务、网络环境、设备故障等原因产生的责任，由相应责任方承担。

软件作者在法律允许的范围内不对用户使用本软件产生的直接或间接损失承担责任。

本软件无法保证第三方设备、浏览器或网络环境绝对无法保存、缓存、复制或获取视频内容。

详细内容请查看：

```text
用户须知与免责声明.md
```

---

## Bug / 问题反馈

如果发现：

* Bug
* 异常行为
* 安全问题
* 滥用行为
* 盗取行为
* 欺诈行为

请联系作者。

**Email：**

[xinyuwang668@gmail.com](mailto:xinyuwang668@gmail.com)

反馈 Bug 时，如果条件允许，请提供：

1. Windows 版本
2. 软件版本
3. 操作步骤
4. 错误信息
5. 截图

---

## 开源协议

本项目采用 MIT License。

详细内容请查看：

```text
LICENSE
```

---

## 作者

**xinyuwang668**

Email:

[xinyuwang668@gmail.com](mailto:xinyuwang668@gmail.com)

---

## Disclaimer

This software is provided for personal and legitimate use.

The developer is not responsible for illegal, unauthorized, infringing, abusive, fraudulent, or otherwise improper use of this software.

Users are responsible for the content they share and for complying with applicable laws and third-party service terms.

