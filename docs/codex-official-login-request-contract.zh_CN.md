# 官方 Codex 登录请求与锐捷迁移边界

核对日期：2026-09-17。依据本次读取的官方 `openai/codex` main 源码、官方 App Server 文档，以及本地 new-api 实现。官方主分支不等同用户当前安装包版本；未执行官方真实登录抓包。范围为浏览器 OAuth 登录、续期、退出，并附设备码分支；不把模型、插件、遥测、静态资源请求算作登录协议请求。

## 1. 先纠正 POST /oauth/authorize 的归属

核对的官方客户端浏览器登录实现中，没有 POST /oauth/authorize 调用。客户端构造授权 URL，由浏览器访问；回调之后客户端 POST /oauth/token。

这不能证明官方认证网站内部绝对不会 POST /oauth/authorize。该网站的账户选择、密码、验证码、工作区与同意授权等提交属于另一层网页实现；本次没有其网络记录，具体方法和路径保持未确认。

当前 new-api 的授权表单明确 POST /oauth/authorize，是本项目的网站实现选择，不能反推为官方 Codex 客户端要求的同名 POST。

## 2. 浏览器流程中已确认的协议请求

官方源码默认 issuer 为 https://auth.openai.com，可被配置覆盖。

| 请求 | 发起者 | 触发及职责 |
| --- | --- | --- |
| GET /oauth/authorize?... | 浏览器 → issuer | 打开客户端生成的授权 URL |
| 官方网页内部请求 | 浏览器 → 官方认证网站 | 身份验证、选择账户/工作区与授权；具体接口未核实 |
| GET http://localhost:{port}/auth/callback?... | 浏览器 → 本机 Codex | 授权服务器重定向后带回 code/state，或授权错误 |
| POST /oauth/token，authorization_code | Codex 内核 → issuer | 表单提交 code、verifier、client_id、redirect_uri，取得 OAuth 凭据 |
| POST /oauth/token，token-exchange | Codex 内核 → issuer | 表单提交 ID Token，尝试换 API Key；该步骤失败可被忽略 |
| GET 本机 /success 或托管成功页 | 浏览器 | 正常流程保存凭据后展示完成页，取决于配置和账户情况 |
| POST /oauth/token，refresh_token | Codex 内核 → 刷新端点 | JSON 提交刷新凭据，用于续期 |
| POST /oauth/revoke | Codex 内核 → 撤销端点 | JSON 请求撤销；优先 refresh token，无则尝试 access token；失败仍可清理本地凭据 |

授权请求携带 client_id、response_type、redirect_uri、scope、state、code_challenge、code_challenge_method，另有客户端扩展参数。Token 交换接口的请求与响应格式属于客户端兼容契约。

默认回调端口为1455，当前官方源码另有1457回退。占用端口处理还可能发送本机 GET /cancel；这是本机协调机制，不是远程授权服务接口。

官方来源：[浏览器登录实现](https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/server.rs)、[刷新实现](https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/auth/manager.rs)、[撤销实现](https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/auth/revoke.rs)、[成功页选择](https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/success_page.rs)。

## 3. 桌面与内核之间的接口不等于远程 HTTP

account/login/start 启动登录并返回 authUrl；account/login/completed 与 account/updated 是通知。account/read 读取账户态，可要求先刷新。account/login/cancel 和 account/logout 分别取消与退出。它们不应被实现成 new-api 的同名 HTTP 路由。

来源：[官方 App Server 认证文档](https://learn.chatgpt.com/docs/app-server)。

## 4. 设备码是另一个分支

设备码登录使用 POST /api/accounts/deviceauth/usercode 申请代码、浏览器访问 GET /codex/device、POST /api/accounts/deviceauth/token 轮询结果，再 POST /oauth/token 兑换凭据。这不是截图中的 loopback 浏览器分支；其中的网页内部提交仍未抓包。

来源：[官方设备码实现](https://raw.githubusercontent.com/openai/codex/main/codex-rs/login/src/device_code_auth.rs)。

## 5. 如何迁移到锐捷

| 官方客户端依赖 | new-api / 锐捷侧对应 |
| --- | --- |
| 授权入口 URL | 将 issuer 指向企业授权服务，GET /oauth/authorize 接收参数 |
| 官方网站完成身份和授权 | 由企业登录/Session及自有授权页实现；当前批准按钮 POST /oauth/authorize |
| 浏览器回到 localhost | 保留本机监听，后端重定向到经过校验的 redirect_uri |
| authorization_code 换 Token | OAuthToken → ExchangeAuthorizationCode，保持字段、表单格式、PKCE和一次性消费 |
| 官方可选 API Key token-exchange | 当前 new-api 未支持该 grant；普通 codex-token 通过企业自定义回调字段取得，属于不同实现 |
| refresh_token 续期 | OAuthToken → Refresh，支持 JSON |
| 撤销 | OAuthRevoke → Revoke；当前客户端 JSON 与后端表单解析差异尚待处理 |
| 本地成功页/本地 RPC | 保留客户端能力；如启用托管成功页，另行配置企业落点 |

本地证据：[授权表单](/Users/w/ruijie/new-api/controller/oauth_authorize_page.go:221)、[OAuth 路由](/Users/w/ruijie/new-api/controller/oauth_server.go:93)、[企业回调扩展](/Users/w/ruijie/new-api/controller/oauth_server.go:155)、[Token grant 分发](/Users/w/ruijie/new-api/controller/oauth_server.go:174)、[撤销解析](/Users/w/ruijie/new-api/controller/oauth_server.go:228)。

兼容工作的依据应是客户端输入输出契约。官方认证网站内部的每个按钮和 HTTP 路径，不需要机械复制。若要回答用户某次官方登录中所有实际网页请求，还需要对应版本的一次浏览器网络观察；只能记录方法、脱敏路径、状态码和跳转关系，不记录真实 Cookie、授权码、Token、state 或 verifier。
