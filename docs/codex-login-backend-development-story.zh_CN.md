# 从理解 Codex 登录到开发 new-api 授权后端

核对日期：2026-09-17。依据 `/Users/w/codex_0_2_6`、`/Users/w/ruizhi`、`/Users/w/ruijie/new-api` 当前源码。

本文按学习者提供的“先理解 Codex，再开发对应后端”的顺序组织工程复盘。它解释开发决策之间的因果关系，不代表逐条验证了个人历史提交顺序。本次仅核对源码和已有测试代码，未执行真实 SSO、桌面登录、生产数据库或模型请求。学习状态保持进行中。

## 1. 起点：明确最终要让什么成立

目标是让企业用户通过公司身份登录 Codex，并让后续模型请求归属 new-api 中正确的本地用户，衔接权限与额度。

因此先分清三个结果：

- 浏览器在 new-api 已登录：new-api Session 能识别本地 User.Id。
- Codex 有本地登录态：本机收到并保存 OAuth 凭据，AuthManager 加载后可向桌面返回账户状态。
- 模型请求成功：模型 provider 有可用的网关凭据，网关校验用户、权限和额度并成功转发。

网页显示登录成功，不足以证明第二个结果也成立。

## 2. 先读客户端，整理完整协议约定

第一遍不按目录通读，而是从登录入口一直追到凭据保存、刷新和退出。每到一个边界，就记录执行者、目标地址、HTTP 方法、Content-Type、字段、返回格式和错误分支。

### 2.1 点击登录后，本机已经负责什么

桌面端调用本地 JSON-RPC `account/login/start`。App Server 的 `login_chatgpt_response` 调用 `run_login_server`，生成 state、PKCE 参数，监听 localhost 回调，并返回 authUrl/loginId。

源码：[account_processor.rs](/Users/w/codex_0_2_6/codex-rs/app-server/src/request_processors/account_processor.rs:532)、[run_login_server](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:162)。

得到的结论：本机已负责生成 state/verifier/challenge、接收 localhost 回调、保存凭据和通知界面。new-api 不需要实现 account/login/start，也不应在远程服务器上实现 localhost:1455 的回调接收器。

### 2.2 浏览器将访问什么地址

`build_authorize_url` 组成 issuer + `/oauth/authorize`，带上 client_id、response_type=code、redirect_uri、scope、state、code_challenge、code_challenge_method=S256 等参数。

源码：[build_authorize_url](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:572)。

得到的结论：企业服务必须有 GET /oauth/authorize，理解这些参数，识别当前用户，并最终把授权结果送回请求指定且经过校验的回调地址。

### 2.3 本机回调要求服务器返回什么

Codex 先比较回调 state 与本机原值，再读取 code。企业适配还读取 codex-token，尝试保存模型 provider 配置。

源码：[回调处理](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:340)。

得到的结论：new-api 必须原样带回 Codex 提供的外层 state，并签发可兑换的授权码。codex-token 是当前企业扩展，不是标准 OAuth 回调必需字段。

### 2.4 拿到 code 后，本机会发什么请求

Codex 直接 POST /oauth/token，使用 application/x-www-form-urlencoded，字段为 grant_type=authorization_code、code、redirect_uri、client_id、code_verifier。返回 JSON 顶层必须有当前客户端解析所需的 id_token、access_token、refresh_token 字符串。

源码：[exchange_code_for_tokens](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:1023)。

得到的结论：不能只返回 success=true，也不能套平台惯用的 data 包装；后端必须理解 code 与 challenge 的关系，并返回客户端真正可以解析的凭据格式。

### 2.5 登录之后还会发生什么

- 刷新：仍是 POST /oauth/token，但 grant_type=refresh_token，客户端发送 JSON。
- 撤销：POST /oauth/revoke，当前客户端发送 JSON，带 token、token_type_hint，以及适用时的 client_id。
- 账户读取：本地 account/read 从 AuthManager/provider 的账户状态构造结果，按请求可能先刷新 Token；不能直接等同为远程 GET /account。
- API Key token-exchange：Codex 还尝试用 ID Token 在 /oauth/token 换 openai-api-key；当前 new-api 不支持该 grant，客户端用 .ok() 忽略这一步失败。企业 codex-token 的取得走回调桥接。

源码：[刷新请求](/Users/w/codex_0_2_6/codex-rs/login/src/auth/manager.rs:1336)、[撤销请求](/Users/w/codex_0_2_6/codex-rs/login/src/auth/revoke.rs:97)、[本地账户读取](/Users/w/codex_0_2_6/codex-rs/app-server/src/request_processors/account_processor.rs:1016)、[可选 API Key 交换](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:1350)。

这一轮阅读的产物应当是协议清单和时序图，而不只是“知道用了 OAuth”。特别要记住：相同 URL 的不同 grant，可能有不同请求体格式。

### 2.6 Codex 具体怎样认定自己有登录态

这里限定为本项目讨论的浏览器 OAuth 登录分支；Codex 还支持 API Key 等其他认证方式。

正常登录链为：本机回调校验 state → 使用 code/verifier 换取 Token → 解析 ID Token → 将 auth_mode=chatgpt、tokens、account_id、last_refresh 写入配置选定的凭据存储 → 登录服务器完成正常成功路径 → App Server 发出 account/login/completed → 重新加载 AuthManager 并发出 account/updated。

OAuth 凭据存储可以是文件、系统密钥存储或自动选择模式，不能一概说成写到 config.toml。config.toml 中的企业 provider/API Key 配置是另一条写入路径。

源码：[凭据保存](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:1100)、[登录完成判定](/Users/w/codex_0_2_6/codex-rs/app-server/src/request_processors/account_processor.rs:563)、[完成通知与重新加载](/Users/w/codex_0_2_6/codex-rs/app-server/src/request_processors/account_processor.rs:808)。

之后，桌面通过本地 account/read 请求账户状态。get_account_response 按参数先尝试刷新，然后调用 provider.account_state；后者在 requires_openai_auth=true 时读取 auth_cached，并排除该凭据已记录永久刷新失败等情况，最后从凭据形成账户结果。这里不是每次请求远程 GET /account 或 /oauth/userinfo 来判断登录。

- 本地没有可用缓存凭据时，账户结果可为 null。
- 浏览器 OAuth 凭据分支返回 Chatgpt 类型，邮箱来自 ID Token；账户类型名称是客户端兼容结构，不表示认证一定由 OpenAI 服务器完成。
- 账户分类从 TokenData 取得。缺少 chatgpt_plan_type 时可回落到 Unknown，不能描述为必须拥有某个付费 plan 才能登录；若连账户 TokenData 都不可用，则可能返回账户详情缺失错误。
- 该本地状态读取不等于服务端逐次有效性确认。实际访问仍须由 new-api 校验凭据；刷新失败、撤销、账户停用和额度不足各有不同表现。

源码：[account/read 实现](/Users/w/codex_0_2_6/codex-rs/app-server/src/request_processors/account_processor.rs:1016)、[provider.account_state](/Users/w/codex_0_2_6/codex-rs/model-provider/src/provider.rs:293)、[plan 的 Unknown 回退](/Users/w/codex_0_2_6/codex-rs/login/src/auth/manager.rs:566)、[启动加载持久化凭据](/Users/w/codex_0_2_6/codex-rs/login/src/auth/manager.rs:1281)。

由此反推后端需求：返回客户端可解析、可保存、可续期的凭据，并在资源请求中真正验证凭据。仅提供一个返回 logged_in=true 的接口，无法替代这条链。

### 2.7 为什么关闭应用再打开，不再显示登录页

本节按文件凭据存储说明。关闭应用结束的是运行中的进程；正常退出程序不等于点击退出账户，磁盘上的 auth.json 保留。再次启动时，新的 App Server 创建 AuthManager，重新读取持久化凭据。FileAuthStorage::try_read_auth_json 打开文件、读字符串并反序列化；AuthManager::new 将 load_auth 的结果放入 CachedAuth.auth。

源码：[启动创建 AuthManager](/Users/w/codex_0_2_6/codex-rs/app-server/src/lib.rs:751)、[文件读取与解析](/Users/w/codex_0_2_6/codex-rs/login/src/auth/storage.rs:181)、[加载为缓存认证状态](/Users/w/codex_0_2_6/codex-rs/login/src/auth/manager.rs:1838)。

桌面快照 26.707.31428 的前端随后通过 getAccount 发出 account/read，参数为 refreshToken:false。正常 OAuth 账户响应含 account.type=chatgpt；前端 lin/uin 将它转为 authMethod=chatgpt，将 requiresOpenaiAuth 转为 requiresAuth。

源码：[账户读取与前端状态转换](/Users/w/ruizhi/docs/app-asar-analysis/26.707.31428/extracted-source/webview/assets/app-initial~app-main~pull-request-code-review~onboarding-page~hotkey-window-thread-page~cha~b76hmflu-y0KJWbm3.js:657)。

决定是否进入登录页的 fY 条件可去除压缩变量名后写为：

```js
if (auth.isLoading) return null;
if (!auth.authMethod && auth.requiresAuth) return "login";
// 认证条件满足后，继续按引导完成状态、工作区等选择 app / welcome。
```

恢复出的 authMethod 为 chatgpt 时，登录分支条件为 false，继续启动流程。之前已完成引导的用户通常进入 app；不是所有首次使用情形都直接跳过 welcome。

源码：[桌面启动路由判断 fY](/Users/w/ruizhi/docs/app-asar-analysis/26.707.31428/extracted-source/webview/assets/app-initial~app-main~page-CtX5-cLy.js:565)。

完整因果链是：前次登录留下磁盘凭据 → 新进程加载凭据 → 本地账户接口返回账户 → 前端得到非空 authMethod → 不进入登录页。这个账户读取没有强制刷新；后续真正访问资源仍会校验 Token，并可能使用 refresh token 无交互续期。明确退出账户会清理凭据并尝试撤销，与单纯退出应用不同。

证据范围：当前本地内核源码及上述版本的解包桌面快照，未重启用户应用进行运行验证，未读取真实 auth.json。

字段层面的关键澄清：上述启动门槛不是重新向服务器证明“这个账户已经认证”。在浏览器ChatGPT/OAuth分支中，auth_mode选择Chatgpt变体，tokens按结构加载，id_token解码出邮箱/账户分类等信息，随后account_state据此形成账户结果。get_current_token_data取得tokens；account_plan_type对存在的TokenData返回分类，缺少plan claim时使用Unknown。access_token与refresh_token作为凭据字符串保存，但该account/read(refreshToken:false)路径没有用它们向远端证明账户有效。

当前token_data.rs中的ID Token加载是JWT结构及payload解析，不进行JWT签名验证。由此恢复出的authMethod可以让前端跳过登录页；实际资源访问是否成功仍取决于服务端对请求凭据的鉴权。不能把“本地恢复账户成功”表述成“启动时已重新验证Token有效”。

源码：[auth_mode分支构造](/Users/w/codex_0_2_6/codex-rs/login/src/auth/manager.rs:258)、[TokenData与分类取得](/Users/w/codex_0_2_6/codex-rs/login/src/auth/manager.rs:566)、[ID Token加载与解码](/Users/w/codex_0_2_6/codex-rs/login/src/token_data.rs:117)。

## 3. 根据协议确定 new-api 的两个角色

面向 Codex，new-api 是 OAuth 授权服务器；面向锐捷 SSO，new-api 是 OAuth 客户端。

这两个角色分别回答：

1. 企业 SSO 帮 new-api 确认当前员工是谁。
2. new-api 根据本地账户和授权决定，给 Codex 签发凭据。

可复用的是平台用户模型、Provider 接口、身份绑定和 Session；要补齐的是面向 Codex 的客户端登记、授权页、授权码、Token 签发、刷新和撤销等服务端职责。

身份连接点是 `(ProviderId, ProviderUserId) → UserOAuthBinding.UserId → users.id`。已有学习记录说明企业主流程在申请阶段预先创建账户与绑定，本次未检查申请系统；本仓库同时保留受注册配置控制的可选创建分支，不能将它当作企业登录时必然注册的行为。

## 4. 先实现授权入口，解决“谁来授权”

边界说明：下面 GET 展示授权页、POST 同一路径提交批准，是当前 new-api 的网页实现。官方登录网页的账户选择、认证、同意授权可能经过多个内部接口，不能凭 UI 截图认定点击账户就发送 POST /oauth/authorize。Codex 的客户端兼容重点是授权入口参数、最终本机回调和 Token 交换；授权网站内部如何处理按钮提交，需要分别查页面实现或实际网络请求。

发现 Codex 让浏览器访问构造出的 /oauth/authorize URL，因此实现 `OAuthAuthorize`：

1. 从受保护的 Session 读取本地用户 ID。
2. 未登录时返回 302 到 /sign-in，classic 主题为 /login。
3. 把原始 /oauth/authorize 路径和 query 编码放入登录页的 redirect 参数，以便身份认证后继续原请求。
4. 已登录时校验客户端、回调地址、scope、PKCE 设置和用户状态，再返回授权页面。

`redirect` 是登录页用于恢复原流程的参数；`redirect_uri` 是 OAuth 客户端的最终回调地址，二者用途不同。

源码：[OAuthAuthorize](/Users/w/ruijie/new-api/controller/oauth_server.go:129)、[redirectToLogin](/Users/w/ruijie/new-api/controller/oauth_server.go:732)、[授权请求验证](/Users/w/ruijie/new-api/service/oauthserver/service.go:636)。

默认 Codex 客户端被登记为 Public，配置允许的 loopback 回调和 scope。PKCE 用于绑定授权与兑换，不靠在桌面程序里共享一个长期 client_secret。[DefaultCodexClient](/Users/w/ruijie/new-api/service/oauthserver/service.go:247)

## 5. 复用企业登录链，得到可以授权的本地用户

此时需要解决：员工如何从“浏览器未登录”变成“Session 中有本地 User.Id”。

现有接口与职责：

| 接口或地址 | 执行者与用途 |
| --- | --- |
| GET /api/oauth/state | 前端请求 new-api，为 new-api → SSO 这一层生成并保存 state |
| SSO 的 authorization endpoint | 前端导航浏览器到企业认证页面，实际地址来自 Provider 配置 |
| /oauth/ruijie | SSO 返回后加载的前端回调页面，不是 Go 的 HandleOAuth |
| GET /api/oauth/ruijie | 前端把 SSO 的 code/state 交给后端；匹配 /api/oauth/:provider |
| SSO 的 token/userinfo endpoint | new-api Go HTTP 客户端访问，兑换 SSO Token、取得员工身份 |

`HandleOAuth` 校验这一层的 state，调用 Provider 的 ExchangeToken/GetUserInfo，查找身份绑定并取得本地用户，最后调用 setupLogin 写入 Session。

源码：[路由注册](/Users/w/ruijie/new-api/router/api-router.go:47)、[HandleOAuth](/Users/w/ruijie/new-api/controller/oauth.go:45)、[setupLogin](/Users/w/ruijie/new-api/controller/user.go:144)。

得到的开发结论：SSO 登录完成后还要恢复原授权请求。只回到 Dashboard，不能让正在 localhost 等待的 Codex 完成登录。这里必须保留外层 state、challenge 等原参数，不能拿内层 SSO 的 state/code 替换它们。

## 6. 用户批准后，建立“用户—授权码—challenge”关系

浏览器 POST /oauth/authorize，携带原请求字段与 decision=approve。后端按以下顺序处理：

1. 从 Session 再次取得用户，校验请求与批准动作。
2. 查找或创建该用户的普通 API Token，名称为 codex-token。
3. 创建一次性授权码，将 code 的哈希、UserId、ClientId、RedirectURI、Scopes、challenge、method、ExpiresAt 等保存为授权码记录，同时维护用户授权记录。
4. 返回 302，Location 指向本机回调并携带 code、原始 state 与企业扩展 codex-token。

源码：[批准与回调](/Users/w/ruijie/new-api/controller/oauth_server.go:151)、[授权码创建](/Users/w/ruijie/new-api/service/oauthserver/service.go:288)、[命名 API Token 复用](/Users/w/ruijie/new-api/model/oauth_relay_token.go:18)。

为什么需要这些数据库字段：下一条 /oauth/token 请求没有浏览器 Session，服务端必须根据授权码记录知道它属于谁、授权给哪个客户端、允许回到哪里，以及 verifier 应满足什么条件。

模型集中在 [model/oauth_server.go](/Users/w/ruijie/new-api/model/oauth_server.go:57)：client、authorization code、access token、refresh token 和 user grant。普通 codex-token 继续属于现有 tokens 表，不能与 OAuth Token 表混为一谈。

## 7. 实现 Token 兑换，让 Codex 真正得到可保存的登录结果

Codex 收到回调后校验外层 state，尝试保存 codex-token 配置，再提交 code+verifier。

new-api 的 POST /oauth/token 根据 grant_type 分发。授权码分支需要：

- 查找授权码记录，拒绝不存在、过期或已消费的 code。
- 校验 ClientId 和 RedirectURI 与授权记录一致。
- 对 verifier 做 S256 计算，与记录的 challenge 比较。
- 校验用户状态。
- 在事务中用 `consumed_at IS NULL` 条件更新并检查 RowsAffected，保证授权码不被重复兑换。
- 签发 Token，返回客户端期待的顶层字段。

源码：[OAuthToken](/Users/w/ruijie/new-api/controller/oauth_server.go:174)、[ExchangeAuthorizationCode](/Users/w/ruijie/new-api/service/oauthserver/service.go:325)、[verifyPKCE](/Users/w/ruijie/new-api/service/oauthserver/service.go:949)。

除了字段名，Token 内部数据也要对齐客户端读取方式：当前实现用 JWT 保存 issuer、subject、audience、有效期等，并提供 Codex 读取的账户字段。这里是兼容客户端的数据结构，不代表赋予官方服务的订阅权益。[signJWT](/Users/w/ruijie/new-api/service/oauthserver/service.go:771)

Codex 随后保存 OAuth 凭据，并由本地 App Server 发出 account/login/completed 通知；这个通知不是 new-api 的 HTTP 接口。

## 8. 补齐续期、退出和辅助能力

登录完成只是一次授权事务结束，长期使用还需要生命周期管理。

- 刷新：POST /oauth/token，grant_type=refresh_token。验证原 refresh token，生成新凭据，将旧 refresh 标记撤销/替换，保持事务一致性。[Refresh](/Users/w/ruijie/new-api/service/oauthserver/service.go:375)
- 输入兼容：初次换 Token 是表单，刷新是 JSON，当前 parseOAuthTokenRequest 同时解析两种格式。[解析器](/Users/w/ruijie/new-api/controller/oauth_server.go:580)
- 撤销：POST /oauth/revoke。服务端已有实现，但当前源码存在下面列出的 JSON/表单差异，不能直接声称和当前客户端完整兼容。
- 辅助：discovery、JWKS、userinfo、introspect、account 与授权管理接口为发现、验签、账户读取和管理提供能力。它们并不等于本次浏览器登录必然逐个调用。

客户端接入时还要对齐登录 issuer、刷新/撤销 URL 和模型 provider base_url。它们属于不同配置入口；打包项目的 [patchCodexAuthIssuerSource](/Users/w/ruizhi/scripts/codex-auth-issuer-source.mjs:40)会统一替换默认授权 issuer 与刷新、撤销端点。

## 9. 接上模型访问，区分两类 Token 的结束点

普通 codex-token 在授权回调里直接传回；OAuth access/id/refresh token 则在 /oauth/token 中取得。

Codex 的 persist_codex_token_setup 设置环境变量并维护 provider 配置；缺少 api_key 时写入，已有 api_key 时当前实现保留旧值。模型请求以该 provider 选出的凭据访问 new-api /v1 接口，网关据 tokens.UserId 识别本地用户，再衔接权限、额度和渠道转发。

源码：[配置保存](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:693)、[已有 api_key 的处理](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:851)、[普通 Token 用户归属](/Users/w/ruijie/new-api/middleware/auth.go:529)。

这也说明验收必须分别观察“Codex 登录态”和“模型请求用户归属”。OAuth 撤销也不能被描述成自动撤销普通 tokens 表里的 codex-token。

## 10. 接口对照总表

| 需求 | 方法与路径 | 服务端入口 | 在故事线中的位置 |
| --- | --- | --- | --- |
| 接收 Codex 授权请求 | GET /oauth/authorize | OAuthAuthorize | 识别登录态、检查参数、展示授权页 |
| 接收批准或拒绝 | POST /oauth/authorize | OAuthAuthorize | 创建授权码、回调 Codex |
| 初次兑换凭据 | POST /oauth/token；authorization_code | OAuthToken → ExchangeAuthorizationCode | 验证 PKCE，签发 Token |
| 登录续期 | POST /oauth/token；refresh_token | OAuthToken → Refresh | 同一路径，不同 grant 与请求体格式 |
| 撤销凭据 | POST /oauth/revoke | OAuthRevoke → Revoke | 已有服务端逻辑，当前输入兼容待验证 |
| 企业 SSO 的 state | GET /api/oauth/state | GenerateOAuthCode | 复用平台 OAuth 登录能力 |
| 企业 SSO 回调处理 | GET /api/oauth/:provider | HandleOAuth | 换 SSO Token、身份映射、建立 Session |
| 授权页面元信息 | GET /api/oauth/authorize/meta | OAuthAuthorizeMeta | 页面辅助，不负责签发 code |
| OAuth/OIDC 发现 | GET /.well-known/oauth-authorization-server；GET /.well-known/openid-configuration | OAuthServerMetadata / OAuthOpenIDConfiguration | 描述协议端点与能力 |
| JWT 公钥 | GET /.well-known/jwks.json | OAuthJWKS | 提供验签公钥 |
| 凭据身份/状态查询 | GET /oauth/userinfo；POST /oauth/introspect | OAuthUserInfo / OAuthIntrospect | 身份与有效状态查询 |
| 账户兼容接口 | GET /account | OAuthAccount | 返回账户结构，不等同本地 account/read |

主路由统一注册见 [RegisterOAuthServerRoutes](/Users/w/ruijie/new-api/controller/oauth_server.go:93) 和 [SetRouter](/Users/w/ruijie/new-api/router/main.go:16)。

## 11. 如何证明开发完成，而不是只证明接口存在

验证分三层：

1. 协议逻辑：错误 verifier、过期 code、重复 code、无效回调、刷新轮换与撤销。
2. HTTP 行为：未登录时 302、授权 GET 返回 HTML、批准 POST 带回正确字段、初次表单与刷新 JSON 的解析、错误响应格式。
3. 真实客户端：首次无 Session 登录、已有 Session 授权、取消、浏览器回调、凭据保存、重启、续期、退出、切换账号与模型请求归属。

相关现有测试：[Service 测试](/Users/w/ruijie/new-api/service/oauthserver/service_test.go:64)、[Controller 测试](/Users/w/ruijie/new-api/controller/oauth_server_test.go:86)。本轮只阅读，未重跑，也不将历史测试结果作为当前真实 SSO 验证。

当前需要保留的边界：

- 撤销格式不匹配：当前 Codex 的 revoke_oauth_token 发送 JSON，而 new-api OAuthRevoke 调用 ParseForm/PostForm 读取字段。本轮确认两端源码格式不同，尚未做运行时复现，不声称撤销端到端通过。
- SSO 后应恢复原授权请求，需要核对各前端入口的 redirect 传递；不能只看到登录 Dashboard 就判定 Codex 登录成功。
- 保存 API Key 时已有值会保留；Token 写入失败也可能只告警并继续 OAuth 登录。因此账号切换与模型凭据归属必须单独验证。
- new-api 当前 /oauth/token 不支持 Codex 可选的 token-exchange grant，企业普通 API Token 通过回调桥接取得。
- PKCE 保护授权码兑换，不保护回调 URL 中直接携带的普通 codex-token；不能把企业扩展称作标准 PKCE 的安全效果。

## 12. 连续讲述版本

我先从 Codex 的登录入口追到本机回调、Token 保存，再继续追刷新和退出，整理出客户端会访问哪些地址、发送什么格式、期待什么响应。我发现本机已经完成 state 和 PKCE 的生成及回调处理，企业侧需要实现的是它所依赖的授权服务器。因此，我以这份协议约定为依据，在 new-api 中复用用户、Session、企业 SSO Provider 和身份绑定能力，先解决员工身份到本地用户的映射，再实现授权入口和批准流程。批准时将用户、客户端、回调地址与 challenge 绑定到一次性授权码，回调 Codex；Token 接口再校验 code 和 verifier，通过事务完成一次性消费，并返回 Codex 能解析的身份与访问凭据。随后补齐刷新、撤销和辅助接口，并接上按用户复用的模型 API Token，使登录身份与网关用户归属衔接。验证时按照服务逻辑、HTTP 契约和真实桌面联调逐层检查，尤其关注请求体格式、跨页面参数保留、凭据保存和账号切换。

使用这段叙述时，新增、复用、改造和验证完成程度应与个人实际工作一致；源码已实现的能力与已完成端到端验证的能力分别说明。

## 13. 只看 new-api 面向 Codex 的服务边界

本节将企业 OA 登录视为一个已有前置能力：它最终让 new-api 获得当前浏览器对应的本地 User.Id。OA 的授权、换码和用户信息请求不属于本节接口清单。

| 从 Codex 观察到的行为 | 推导出的后端工作 | 当前落点 |
| --- | --- | --- |
| 浏览器打开授权 URL | 接收 client_id、回调地址、scope、state、challenge，识别当前用户并展示授权页 | GET /oauth/authorize |
| 用户批准应用访问 | 将用户与客户端、回调地址、challenge 绑定到短期授权码，浏览器重定向到本机 | POST /oauth/authorize |
| 本机提交 code/verifier | 检查授权码与 PKCE，一次性消费并返回 Token JSON | POST /oauth/token，authorization_code |
| 本机解析并保存身份 | 签发兼容的 ID Token，提供稳定账户 ID、邮箱与账户分类字段 | service.signJWT；客户端解析 token_data.rs |
| 过期前或请求要求刷新 | 校验 refresh token、轮换凭据、保持用户归属 | POST /oauth/token，refresh_token |
| 退出需要服务端撤销 | 处理客户端实际发送的内容类型与字段，撤销 OAuth 凭据 | POST /oauth/revoke；当前 JSON/表单差异仍待处理 |
| 登录后请求业务资源 | 校验 access token 或普通 API Token，再执行权限与业务检查 | 对应资源路由的鉴权中间件 |

对本次浏览器登录主链，authorize 与 token 是直接依赖。刷新和撤销覆盖后续生命周期。discovery/JWKS/userinfo/introspect/远程 account 是已实现的协议及兼容能力，不能据路由存在就说它们全是本地 account/read 的依赖。模型、额度、插件、云任务等按所需产品功能分别评估；登录成功不等于所有官方后台能力都已替换。

开发时应分别对齐授权 issuer、Token 刷新/撤销地址、模型 provider base_url，以及所启用账户/后台功能使用的 chatgpt_base_url。`requires_openai_auth` 和 `chatgpt` 等源码名称不会自动把这些地址统一指向某个域名。

可观察的验收链：批准后浏览器收到指向本机的 302 → 本机发出 Token 请求 → 凭据保存与本地完成通知 → account/read 返回账户 → 重启后恢复账户 → 刷新轮换成功 → 撤销后旧凭据被后端拒绝 → 独立验证模型请求的用户归属。只使用脱敏状态和测试夹具，不记录真实 Token、授权码、Cookie 或 verifier。本轮未执行这些运行验证。
