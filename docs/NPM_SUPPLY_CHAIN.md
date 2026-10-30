# npm 与桌面桥接风险控制

状态：2026-09-12 已落实到 React 实现。当前已固定 lock、禁用生命周期脚本、隔离构建，并保存漏洞/签名审核记录。具体证据如下；Windows 发布仍需实机检查，不能承诺零风险。

## 当前证据

- Node 22.14.0 / npm 10.9.2；React 19.2.8、Base UI 1.7.0、Lucide 1.35.0；TypeScript 5.9.3 / esbuild 0.28.2。无 Vite、无 npx registry 初始化，无额外颜色/动画依赖。
- 锁文件 45 个依赖条目，当前平台实际安装 20 个包（包括两处同版本间接依赖）；其余包含其他平台 esbuild 二进制。完整清单见 `frontend/security/dependency-inventory.json`。
- 最新 `npm audit` 含开发依赖：0 个已知漏洞；`npm audit signatures`：20 个注册表签名、13 个 provenance attestation 验证通过。完整输出、时间和 lock 哈希见 `frontend/security/audit-result.json`。其余包没有 attestation，不把这一点描述为全量供应链证明。
- 已读取全部锁定版本的发布记录，14 天冷却期检查见 `frontend/security/release-review.json`。发现过新 `use-sync-external-store` 间接版本后，显式 override 为已核对的 1.6.0，再重建/审计。
- macOS `scripts/safe_build.py` 在独立 deny-by-default 沙箱执行类型检查和构建，禁止网络与个人目录读取；不会因沙箱不可用而退回无限制构建。`ignore-scripts` 阻止 esbuild postinstall，实际使用已下载且哈希固定的平台二进制。
- shadcn 源码固定提交、完整 MIT 声明、离线 Noto Sans SC 字体 SHA-256/OFL 许可见 `frontend/THIRD_PARTY.md`；依赖许可证全文随静态产物打包。
- Windows Python 依赖的 19 个 wheel 已下载校验 hash 和目标环境依赖闭包，未在本机执行 Windows 二进制。`proxy_tools` 原始 sdist 没有 wheel：校验官方原包 SHA-256，读取源码后用自有标准库脚本生成 wheel，未执行 `setup.py`；许可证以官方仓库 BSD-2-Clause 全文为准，不沿用 PyPI 的 MIT 标签。
- `scripts/verify_frontend.py` 检查源文件、锁和产物一致，防止把旧资源打包；它不是签名或安全证明。发布需另外签名并保留产物 hash。

## 不能承诺零风险

包可能在安装脚本、构建插件、运行时三个阶段执行恶意代码。锁文件能防止无意漂移，但也能锁住恶意版本；签名与 provenance 能核对来源，却不证明代码无害。知名作者、少量顶层依赖、tree-shaking、复制源码都不等于安全。

React 页面还拥有调用 Python 的入口：一个页面注入漏洞，如果遇到过宽的 Python 接口，危害可能超过普通网站。因此 npm 与 bridge 要一起控制。

## 现在已设置

项目根 `.npmrc`：

```ini
registry=https://registry.npmjs.org/
save-exact=true
package-lock=true
ignore-scripts=true
fund=false
audit=false
```

`audit=false` 只是不让每次安装自动提交依赖信息，并非取消审计。发布流程仍必须显式运行 audit。该命令会向配置 registry 提交依赖名称和版本，因此只对公开前端依赖树执行，不上传项目图片、字幕、私有包或凭据。

若前端放在独立的 `frontend/` 包目录，需要在该包中继承/复制相同配置，并从实际安装目录验证配置生效。不能假设祖先目录 `.npmrc` 永远生效。

## 依赖准入与更新

- 运行依赖以 React、React DOM 和一种 UI 行为底层为主；样式组件源码进入仓库。字体、图标、本地 CSS 与业务状态尽量不引入额外包。
- 不为了几行格式化/颜色转换代码加小包；不使用不明第三方 shadcn registry；不直接执行官网的 `npx ...@latest init`。
- 选择官方项目指向的准确包名、固定版本和许可证；核对仓库、发布者、变更日志、包内容和安装脚本。源码组件记录来源 URL 与固定提交/版本，不只留下复制日期。
- 直接依赖不使用 `^`、`~`、`latest`；提交 package.json、package-lock.json 和工具链版本。传递依赖由锁文件一起固定。
- 新版本原则上观察 7–14 天，再在专门变更中升级；已被利用的安全问题允许加急审查，不机械等待。成熟版本仍可能有漏洞，不能永久不升级。
- 本机目前 npm 10.9.2；不要写入未经验证的新版本 `min-release-age`/脚本白名单选项并声称已保护。冷却期暂按发布记录人工审核，后续接入经验证的 CI 检查。
- 每次更新核对完整依赖树和锁文件变化：新增包、tarball 主机、integrity、弃用、许可变化、install scripts；默认拒绝 git、非 HTTPS、未知镜像和意外 file/link 依赖。
- 漏洞检查覆盖 devDependencies：构建插件在产物生成前拥有执行能力，不能只审查最终运行依赖。

## 安装与构建隔离

依赖经准入且已有锁文件后，常规安装使用：

```sh
# 在 frontend 目录，获取阶段不执行任何安装脚本：
env -i PATH=/usr/local/bin:/usr/bin:/bin npm ci --ignore-scripts --no-audit --no-fund --userconfig=/dev/null --globalconfig=./.npm-empty --cache=/private/tmp/jian-subtitle-npm-cache
# 审核阶段仅向官方服务提交公开依赖信息：
env -i PATH=/usr/local/bin:/usr/bin:/bin node scripts/audit-record.mjs
# 从项目根，在禁止网络/个人目录的沙箱构建：
.venv/bin/python scripts/safe_build.py
```

`npm ci` 在 manifest 与 lock 不一致时应失败，不允许构建时临时改锁。

`ignore-scripts` 阻止安装生命周期脚本，但显式 `npm run build`、npm 工具命令及加载的插件仍会运行代码。审查 build/test 配置后，在隔离环境运行；不要把这个开关称作沙箱。[npm ci 文档](https://docs.npmjs.com/cli/v10/commands/npm-ci/)

Vite 等工具的本地二进制可能需要安装步骤。先验证是否可在禁脚本下运行；确需例外时，只对已审查的具体包、版本和 integrity，在无凭据隔离构建环境执行必要步骤并记录，不能全局改成 `ignore-scripts=false`。

审计网络失败、签名失败、缺少证明和“审计通过”必须分开记录。不要 `npm audit fix --force` 自动升级生产依赖。audit 检查已知漏洞，signatures 检查签名/来源，均不能排除未发现的恶意代码。[npm audit 文档](https://docs.npmjs.com/cli/v10/commands/npm-audit/)

以上隔离启动器适用于当前 macOS。Windows 打包可使用已核对的静态产物，不执行 npm；重新编译前端必须在不含个人文件/凭据的隔离 VM 或专用构建环境进行。构建机只挂载所需源码，不挂载个人 Home、SSH、浏览器资料、云凭据或生产图片；获取审核包与执行构建分阶段。签名凭据隔离到最后的签名作业。

发布保留 SBOM、许可证清单、锁文件、工具链版本、审计结果、构建日志及产物 SHA-256。清洁构建复现测试不等于已经达到字节级可复现构建。

## 运行时与 Python bridge

- 安装包只带编译后的 HTML/CSS/JS 和 Python 运行资源；用户运行时不安装 npm 包，不带 Node 服务，不依赖 CDN、在线字体或远程脚本。
- 限制 WebView 导航到应用自身受控地址；当前版本禁止远程跳转、文件 URL 和下载，没有提供任意外链打开入口。
- 发布关闭 debug/devtools，不启动 Vite 开发服务器；CSP 默认仅允许本地资源，禁止远程脚本与任意 eval。pywebview 注入脚本所需的 nonce/hash/受控样式例外要实测，不能为了跑起来无限放宽 CSP。
- API 采用小型白名单：选择图片/目录、读项目快照、提交领域命令、请求预览、启动/停止/查询导出。不要暴露 `eval`、shell、任意路径读写、通用“执行 Python”方法。
- Python 端严格校验命令类型、大小、范围、资产 ID、项目 ID、revision 和任务 ID。TypeScript 类型不能代替后端校验。
- 前端用不透明 assetId/fontId/outputToken 访问经用户选择的资源；规范化路径后再次检查授权根、符号链接、扩展名和输出不可覆盖源图。
- 文件名/字幕/说话人只能作为普通文本渲染，禁止 dangerouslySetInnerHTML；不能把它们拼接为 JavaScript、shell 或 URL。
- 如使用 localhost HTTP 服务，只绑定 loopback；校验 Host/Origin 与每次启动的会话令牌，所有有副作用请求防 CSRF，不能认为 localhost 天然安全。[pywebview 安全说明](https://pywebview.flowrl.com/guide/security.html)

这些约束降低攻击面，不是对所有依赖或 WebView 的安全保证。发现上游包被污染时，应暂停构建、隔离环境、审查受影响产物，必要时更换在构建中暴露过的凭据。

当前运行边界：随机回环端口、256-bit 会话令牌、Host/Origin 检查、严格 CSP（无 eval）、1 MiB 请求上限、12 个并发连接和 10 秒连接超时；js_api 不暴露通用 Python 对象。拖入文件路径只来自 OS/WebView2 的原生文件对象，前端伪造的 fullPath 不授予权限。来源授权和恢复任务存放在应用目录的 HMAC 封装记录里，不能靠改项目 JSON 获得任意路径访问。

这些措施不防御已控制当前 OS 用户账户、可读取应用密钥或改写安装目录的攻击者。Pillow/OpenCV/WebView 仍含原生代码，未来未知漏洞和上游污染不能被现有 audit 排除。不要关闭系统杀毒或系统安全更新；Microsoft WebView2 Evergreen 的更新策略按系统管理，不能声称整个 WebView 运行时绝不联网。
