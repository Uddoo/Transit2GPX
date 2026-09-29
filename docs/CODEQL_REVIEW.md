# CodeQL 首轮告警审阅

审阅日期：2026-09-29。基线为 `497f6ec6fc8fcbb1b55edeae9b46988b0333c104`，对应 v1.0.0；[首次扫描](https://github.com/Uddoo/Transit2GPX/actions/runs/36541019964)采用扩展规则与 `remote_and_local` 模型。逐条读取了 Python SARIF 中的来源到调用点数据流，不能把 severity 标签直接当作已确认的可利用漏洞。

## 修复与加固

| 告警 | 原因与处理 |
|---|---|
| #1、#2、#3 | `astral-sh/setup-uv` 使用可移动 major tag。固定到上游 v6 对应的完整提交 SHA；同时固定工作流中的其余 Actions。 |
| #4 | `softprops/action-gh-release` 使用可移动 v2。固定到上游对应的完整提交 SHA。 |
| #9 | selector 写入已有版本名白名单，但激活流程在白名单检查之前已访问目录；目录软链接也可能越出图根目录。现在先验证非保留的单段版本名，再解析并验证目录边界；selector 替换和回滚同样检查目标目录。 |
| #10 | E2E 脚本从环境变量回读路径，实际上该值已在同一进程中无条件设为仓库的 `frontend/dist`。删除冗余环境回读，直接复用同一常量。 |
| #13、#14 | HSTORE key/value 正则的反斜杠分支与普通字符分支重叠，畸形输入可导致指数回溯。替换为始终向前推进的线性扫描，保留 Unicode、引号/反斜杠转义、空值和重复键覆盖语义。 |
| #19 | 铁路验收 CLI 声称只访问 loopback，却使用接受任意 URL、环境代理及自动重定向的客户端。现在只允许 HTTP loopback 的指定 sidecar 端点；localhost 映射到固定回环地址，禁用环境代理，不跟随重定向，保留 404 时的 Metro2Fog metadata 回退。 |

固定的 Action SHA 通过各上游仓库的 Git tag API 核对；setup-uv 的 annotated tag 已进一步解引用到 commit。没有通过移除扫描语言、降低规则集或内联忽略注释掩盖结果。

## 需要按信任边界处理的 10 条告警

以下来源在 `remote_and_local` 模型下被统一视为不可信，但它们是本地操作者显式配置的路径或程序。单纯限制为应用安装目录会破坏已有数据、便携 Java、自定义编译器和备份位置。这里的结论限于**可信本地操作者、单用户 loopback 应用**，不适用于公网服务或多用户隔离环境。

| 告警 | 数据流与判断依据 |
|---|---|
| #5 | 本地 `ProgramFiles` / `ProgramFiles(x86)` 环境变量 → `Inno Setup 6/ISCC.exe` 的存在检查。用于查找操作者已安装的编译器，没有请求参数、归档文件名或远端输入进入该分支。 |
| #6、#7 | CLI/本地导入 API 中显式选择的数据根目录 → 目录发现与审计结果中的规范化根目录。跨磁盘导入是产品功能；`resolve()` 在此是规范化，不是权限隔离。API 的浏览器请求边界已补强，见下文。 |
| #8 | 本地 `backup --output` → 操作者选择的备份 ZIP 路径。支持任意本地备份位置是维护接口的契约；备份脚本仍拒绝覆盖已存在的目标。 |
| #11、#12 | 操作者提供的 `RAIL_JAVA_HOME` → 固定的 `bin/java[.exe]` 路径及文件存在检查。这是显式 Java 选择能力，不能据此推断攻击者可以控制该环境变量。 |
| #15 | 构建 CLI 的 `--iscc` 或 ProgramFiles 中找到的编译器 → `subprocess.run` 的 argv 列表。执行操作者选择的编译器是命令的目的；默认 `shell=False`，没有拼接后交给 shell 执行。 |
| #16 | 上述 Java 选择结果 → `[java, "-version"]`。是对已配置运行时的版本检测，不是把用户文本作为命令表达式解释。 |
| #17、#18 | 上述 Java 选择结果 → Windows/POSIX 的 `Popen` argv 列表。固定 `java[.exe]` 文件名、分离参数且不使用 shell；保留显式 JAR、Java 和 Java 参数配置，它们必须来自可信本地操作者。 |

本次不自动 dismiss 这 10 条告警。修复发布后，应结合新扫描的数据流核对并逐条填写上述适用前提；不能仅因它们来自本地输入就无条件认定安全，也不能将旧基线的告警声称已经修复。

## 本地 API 的额外边界修复

审阅目录与 Java 配置告警时发现，仅绑定 loopback 尚不足以信任浏览器请求。新增 Host / Origin / Fetch Metadata 校验：

- 只接受 `127.0.0.1`、`localhost`、`[::1]`，拒绝借助外部域名进行 DNS rebinding 的 Host。
- 有 Origin 的请求必须与 Host 的 scheme、hostname、port 相同；拒绝 `Origin: null`、不同端口或外站来源。
- 拒绝 `Sec-Fetch-Site: cross-site`，包括没有 Origin 的跨站导航。
- 保留没有浏览器 Origin 的本地 CLI 调用，以及 Vite 代理保留 Host 时的同源开发请求。受拒绝请求仍由既有 request-id 中间件分配标识。

这不是身份认证。其他可执行任意代码的本地进程仍属于可信操作者边界；不要将服务暴露到公网、作为多人共享后端，或把不可信的 Java/JAR/编译器目录填入配置。显式配置为非 loopback 域名的反向代理不在本次支持范围内。

## 回归验证

- 新增长反斜杠输入的子进程超时回归，避免回归为原正则时卡死测试进程。
- 覆盖恶意 Host、外站/空 Origin、跨端口请求、IPv4/IPv6 同源、CLI 和 request-id。
- 用真实本地 HTTP 测试服务覆盖禁止重定向、忽略代理、旧 metadata 回退；危险目标在建立连接前拒绝。
- 覆盖图版本路径穿越、保留名称、越界软链接；Windows 无创建软链接权限时该用例明确跳过，由支持 symlink 的环境执行。
- 保留备份、导入、Java 自定义路径、铁路图元数据和全栈行程/GPX 的既有回归。

本记录区分本地修复与 GitHub 状态：未推送的代码不会关闭 main 上的告警。完成提交和推送后，需重新检查同一提交的 CodeQL 与 CI；v1.0.0 标签及已发布附件不应被移动或替换。

本次已执行 `transit2gpx.ps1 backend-check`：Ruff、格式检查、mypy 通过，209 项测试通过、1 项 Windows symlink 权限跳过，覆盖率 87.81%。随后追加的自定义 Java 路径回归随 `test_sidecar_supervisor.py` 5 项测试全部通过。`transit2gpx.ps1 e2e` 的 38 项浏览器测试和 1 项真实全栈行程/GPX 测试通过，生产构建通过。尚未执行远端修复后 CodeQL 复扫。
