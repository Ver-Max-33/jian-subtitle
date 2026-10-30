# 发布与自动更新

## 发布一个版本

```bash
.venv/bin/python scripts/release.py version 0.3.0
git commit -am "简幕 0.3.0"
git tag v0.3.0
git push origin main v0.3.0
```

推送标签后，GitHub Actions（`.github/workflows/release.yml`）在 Windows 上跑测试、打包，为安装包生成构建证明，然后建一个**草稿** release。草稿对用户不可见。到 GitHub 上看一眼草稿，改好更新说明（应用里的更新窗口会显示这段文字），然后在本机运行：

```bash
.venv/bin/python scripts/release.py publish v0.3.0
```

它会下载草稿里的安装包，用 `gh attestation verify` 确认安装包是 release 工作流在 GitHub 托管的机器上、从你本地这个标签对应的提交构建的，然后生成 `update.json` 并用你的私钥签名（这时会要求输入口令），上传后把草稿改为正式发布。已安装的简幕下次启动时就会看到更新。

想先试构建、不发布：在 GitHub 的 Actions 页面手动运行 release 工作流，安装包会保留 7 天，作为这次运行的附件。

## 第一次发布前

1. 生成更新签名钥匙（只做一次）：

   ```bash
   .venv/bin/python scripts/release.py keygen
   ```

   私钥存在 `~/.config/jian-subtitle/update-signing-key.pem`，权限 600，口令加密。公钥写进 `src/subtitle_app/update_key.py`，提交它。没有公钥时 CI 会拒绝发布。
2. **备份私钥文件和口令**（放进密码管理器）。丢了它，已安装的版本就再也收不到自动更新，只能让用户手动重装。
3. 需要 OpenSSL 3（`brew install openssl@3`；macOS 自带的 LibreSSL 不支持）和已登录的 `gh`。
4. 建议在仓库 Settings → General 里开启 **Release immutability**：发布后安装包和标签都不能再被替换。

## 安全设计

- **签名钥匙不在 GitHub 上。** 构建在 CI，签名在维护者本机。即使 GitHub 令牌泄漏、某个 Action 被篡改或有人替换了 release 里的文件，也做不出能被应用接受的 `update.json`。
- **应用只信编译进去的公钥。** `update.json` 先验 Ed25519 签名（`src/subtitle_app/ed25519.py`，按 RFC 8032 实现，用 RFC 测试向量和 OpenSSL 交叉验证），再严格检查字段：版本号、文件名、大小、SHA-256。下载地址由版本号推出，不从文件里读。
- **只走 HTTPS**，证书照常校验，跳转也不能离开 HTTPS。下载时边下边算 SHA-256，大小或哈希不符就删除；启动安装程序前再算一次。
- **不会降级**：只接受比当前版本新的版本。
- **CI 权限最小**：构建任务只读、没有密钥；发布任务不检出、不运行仓库代码，只把构建好的文件当数据上传。所有 Action 都固定到完整提交 SHA。
- 安装包本身还没有 Windows 代码签名，第一次从浏览器下载安装时 SmartScreen 会提示“未知发布者”。应用内更新不经过浏览器，不受影响。以后可以申请 SignPath（开源项目免费）或 Azure Artifact Signing 来签名。

## 应用里的行为

- 只有安装好的 Windows 版本会检查更新；开发环境、浏览器预览和没有公钥的构建都不联网。
- 启动时在后台检查一次（`https://github.com/Ver-Max-33/jian-subtitle/releases/latest/download/update.json`）。可以在更新窗口里关掉“自动检查更新”，设置存在数据目录的 `update-settings.json`。
- 发现新版本时弹出提示；菜单里也有「检查更新…」。点「立即更新」后下载到数据目录的 `updates/`，校验通过就开始安装：简幕关闭，安装程序只显示进度条，装完自动重新打开简幕。下载时点「后台下载」可以继续工作，下好后再提示「重启并更新」。项目每次修改都已保存，不会丢失。导出、批量处理或导入进行时不能安装。
- 更新窗口显示 release 的说明文字；发布脚本会把 GitHub 的 Markdown 转成纯文本再签名。
