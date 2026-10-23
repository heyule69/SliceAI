# Windows 安装包代码签名

SliceAI 的交付物是 Windows 安装包。仓库不包含证书、私钥或签名后的安装包。没有证书时不要自行生成测试证书充数，也不要把未签名的文件写成已经签名。

未签名的 `SliceAI_0.2.0_x64-setup.exe` 在其他电脑上可能被 Windows SmartScreen 拦截，提示“Windows 已保护你的电脑”或未知发布者。用户可以查看“更多信息”后仍选择运行，但这不是签名。SmartScreen 声誉要等用受信任证书签名并有实际安装量之后才会改善，本仓库不能提前消除这个提示。

## 什么时候签

只在发布者已经有可用的 Authenticode 证书时签名。证书应是受信任的代码签名证书（公钥在证书文件里，私钥由发布者保管）。OV 或 EV 都可以用来签名；EV 通常能更快降低 SmartScreen 的拦截，但本清单不要求购买特定一种。

需要同时具备：

- 安装包已由当前源码通过 `npm run bundle` 生成，路径默认为 `src-tauri/target/release/bundle/nsis/SliceAI_0.2.0_x64-setup.exe`。
- Windows SDK 里的 `signtool.exe` 在 PATH 中，或调用时显式传入。
- 证书 PFX（或可用的证书存储）。PFX 密码不要写进仓库、命令行历史或 CI 日志。

## 操作清单

1. 在将要交付的那台构建机上确认安装包路径和文件大小，先做 `scripts/package-release.py --verify-only`，确认要签的是这次构建的安装包。
2. 把 PFX 放在仓库之外。设置环境变量，不要把密码写进参数文件并提交：
   - `SLICEAI_SIGN_PFX`：PFX 的绝对路径。
   - `SLICEAI_SIGN_PASSWORD`：PFX 密码。没有密码的证书可以留空，但脚本不会因此去弹出交互窗口。
3. 先看计划，不签名：

```powershell
python -X utf8 scripts/sign-installer.py --dry-run
```

没有配置证书时，这条命令退出码为 0，结果里 `signed` 为 false，并说明 SmartScreen 风险。它不会创建证书，也不会改安装包。

4. 有证书后再签。时间戳让签名在证书过期后仍然可以被验证：

```powershell
python -X utf8 scripts/sign-installer.py --installer src-tauri\target\release\bundle\nsis\SliceAI_0.2.0_x64-setup.exe
```

等价的手工命令（密码用你自己的方式传入，不要提交）：

```powershell
signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f C:\secrets\sliceai.pfx /p $env:SLICEAI_SIGN_PASSWORD src-tauri\target\release\bundle\nsis\SliceAI_0.2.0_x64-setup.exe
signtool verify /pa /v src-tauri\target\release\bundle\nsis\SliceAI_0.2.0_x64-setup.exe
```

5. 签名成功后再运行 `python -X utf8 scripts/package-release.py --require-alignment`。收集脚本复制的是签名之后的安装包，并把签名后的字节写入 `release/SHA256.json`。先收集再签名的话，校验和会和交付文件不一致。
6. 在一台没有安装过该发布者证书的 Windows 电脑上双击安装包，确认签名页显示的发布者名称，并记录 SmartScreen 是否仍提示。记录结果，不要把“已签名”写成“SmartScreen 不再提示”。

## 没有证书时

- 发布流程可以继续，安装包保持未签名。
- `scripts/sign-installer.py` 默认退出码 0，JSON 里 `signed` 为 false。
- 若这次发布必须签名，加上 `--require`。没有可用证书、PFX 路径不存在、密码缺失或找不到 `signtool` 时命令失败，并且不会把安装包标成已签名。
- `scripts/package-release.py --sign` 同样只在配置了证书时调用签名；没有证书则继续收集未签名安装包。`--require-signature` 会在替换 `release/` 之前失败，旧的发布目录保持不动。

不要把自签证书、临时 PFX 或证书密码放进 Git。CI 不持有证书，也不会为了通过检查而签名。
