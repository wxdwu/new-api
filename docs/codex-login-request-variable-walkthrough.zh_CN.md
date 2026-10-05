# Codex → new-api → 锐捷SSO：登录请求与变量逐步追踪

核对日期：2026-09-05。Codex源码根目录为 `/Users/w/codex_0_2_6`，HEAD为 `d34bc57f9`；new-api源码根目录为 `/Users/w/ruijie/new-api`，HEAD为 `ff6554ee8`，以下以当前工作树为准。用户手绘图作为待核对的流程说明，不作为程序行为的证据。

本次完成源码核对与new-api OAuth定向测试；未进行真实SSO登录、Desktop回调、生产数据库或上游模型验证。本文示意值均为符号，不包含真实凭据。学习状态：进行中。

生产流程补充（2026-09-05，由学习者确认）：员工申请阶段已经通过事务完成new-api账户创建及现有OA身份绑定；SSO登录使用已有绑定，不在登录时注册账户。本次尚未检查申请服务的写入实现，下面区分该业务事实与当前仓库中可见的登录读取逻辑。

## 1. 先明确执行者与两层OAuth

| 参与者 | 在本次登录中的工作 |
| --- | --- |
| Desktop界面 | 发起本地JSON-RPC登录请求，接收authUrl/loginId，打开浏览器，展示登录通知 |
| Rust app-server | 处理account/login/start，组织登录任务，接收完成结果并通知界面 |
| Rust LoginServer | app-server进程中的本机HTTP服务，生成state/PKCE，接收localhost回调，直接请求new-api换Token并保存凭据；不是另一台远程服务器 |
| 浏览器 | 访问new-api和SSO网页，保存各自域名的Cookie，执行前端JS、表单提交和HTTP重定向 |
| new-api | 对SSO是OAuth Client；对Codex是OAuth Server；另提供模型网关与计费 |
| 锐捷SSO | 完成员工认证，签发它自己的授权码与access token，提供userinfo |
| 数据库 | 保存new-api用户、OAuth绑定、客户端、授权码、Token、授权许可和计费事实 |
| Redis | 可选缓存/限流设施；当前Cookie Session与OAuth事实不默认依赖Redis保存 |

图2是桌面端发起登录的局部图；图1将new-api与企业SSO加入这个过程；图3是登录完成后独立的模型请求。

两层OAuth分别是：

- 外层：Codex（Client）→ new-api（Authorization Server），本文记为 `outer_state`、`codex_code`。
- 内层：new-api（Client）→ 锐捷SSO（Authorization Server），本文记为 `inner_state`、`sso_code`。

这些名字是为了教学消歧。真实请求中两层都使用字段名 `state` 和 `code`，必须结合发送者、接收者和URL识别。

## 2. 内核改造接入了哪些配置点

当前 [login/server.rs](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:58) 中：

- 默认登录issuer为 `https://gptauth.ruijie.com.cn`，用于拼接 `/oauth/authorize` 和初次 `/oauth/token`。app-server允许 `chatgpt_login_base_url`覆盖它。
- 回调参数 `codex-token`触发锐捷provider配置安装：选择 `ruijie-uniapi`、设置 `RUIJIE_UNIAPI_KEY`、补充provider配置。
- 新增provider的默认base_url为 `https://gptauth.ruijie.com.cn/v1`，wire_api为 `responses`。后续模型HTTP路径为base_url加 `responses`。
- 登录issuer、模型base_url、刷新/撤销端点是不同配置点；更改其中一个不会自动更改另两个。

基本的本机回调、随机state、PKCE和授权码换Token框架仍在使用。`codex-token`回调桥接是当前锐捷适配链的重要扩展，不能把它描述成标准OAuth必有的字段。

## 3. 请求账本：按首次没有new-api Session的情况展开

| 序号 | 请求执行者 → 接收者 | 请求或响应 | 产生/携带的关键数据 | 接收方下一步 |
| --- | --- | --- | --- | --- |
| 1 | Desktop → 本地app-server | JSON-RPC `account/login/start`，chatgpt登录类型 | 本地RPC request id | 调用login_chatgpt_response，不是访问new-api的HTTP接口 |
| 2 | app-server内部 → LoginServer | `run_login_server` | outer_state、verifier、challenge、actual_port、redirect_uri、auth_url；app-server另生成loginId | 监听本机并等待回调，向Desktop返回loginId/authUrl |
| 3 | 浏览器 → new-api | GET `/oauth/authorize?...` | client_id、redirect_uri、scope、outer_state、challenge、S256 | 从Cookie Session读取本地userID；没有则302到登录页，redirect中带原授权URL |
| 4 | 浏览器前端 → new-api | GET `/api/user/logout` | 当前Cookie（如有） | 当前自定义OAuth启动代码先清理旧的Web登录态，避免进入账号绑定流程 |
| 5 | 浏览器前端 → new-api | GET `/api/oauth/state` | 可选aff | 生成inner_state，存Session的oauth_state，Save写Cookie，JSON返回state |
| 6 | 浏览器 → 锐捷SSO | GET 配置的authorization endpoint | SSO侧client_id、new-api的/oauth/ruijie回调地址、scope、inner_state | SSO执行员工认证/授权；它自己的Cookie仅由它识别 |
| 7 | SSO通过浏览器 → new-api前端 | 浏览器访问 `/oauth/ruijie?code=SSO_CODE&state=INNER_STATE` | sso_code、inner_state | 加载前端回调页；这还不是后端HandleOAuth |
| 8 | 浏览器前端 → new-api后端 | GET `/api/oauth/ruijie?code=...&state=...` | 上一步query、新api域下的Cookie | HandleOAuth先验证inner_state，选择provider |
| 9 | new-api Go HTTP客户端 → SSO | POST 配置的token endpoint | sso_code、SSO client_id/client_secret、redirect_uri、grant_type | SSO验证后返回它的access token；new-api保留在本次请求对象中 |
| 10 | new-api Go HTTP客户端 → SSO | GET 配置的userinfo endpoint | Authorization携带SSO access token | 解析ProviderUserID等字段，查询或创建本地User与Binding |
| 11 | new-api → 浏览器 | setupLogin返回JSON和Set-Cookie | Session里的id/username/role/status/group；前端保存用户展示态 | new-api Web登录成立；还未完成Codex授权码交换 |
| 12 | 浏览器 → new-api | 恢复或重新访问GET `/oauth/authorize?...` | new-api Cookie与原外层参数 | 验证client/redirect/scopes/PKCE配置，展示授权HTML |
| 13 | 浏览器 → new-api | POST `/oauth/authorize` | 原外层参数、decision=approve、Cookie | 创建或复用普通codex-token，再创建一次性codex_code和授权记录 |
| 14 | 浏览器 → 本机LoginServer | 302后GET `http://localhost:1455/auth/callback?...` | codex_code、outer_state、codex-token | 本机校验outer_state，尝试写provider配置 |
| 15 | LoginServer → new-api | POST `/oauth/token`，表单 | authorization_code、codex_code、client_id、redirect_uri、code_verifier | 校验并原子消费授权码，签发OAuth access/id/refresh token |
| 16 | LoginServer → new-api | 再次POST `/oauth/token`，token-exchange grant | ID Token、requested_token=openai-api-key | 当前new-api返回unsupported_grant_type；Codex忽略该错误 |
| 17 | LoginServer → 本地凭据存储 | save_auth | OAuth TokenData、auth_mode、account_id、last_refresh | 按配置保存到文件/钥匙串等后端 |
| 18 | 浏览器与本机；app-server与Desktop | 本机success页或Hosted跳转；`account/login/completed` | loginId、success、error | app-server等待登录任务结束，通知Desktop并重新加载账户状态 |

第12步是需要衔接的流程，不能假定当前每条前端入口都会自动恢复：当前锐捷按钮不传redirect，可能回到Dashboard。已有new-api Session时可以直接跳过内层SSO部分；取消、拒绝授权和错误响应是其他分支。

SSO的确切token/userinfo URL由 `custom_oauth_providers` 配置指定，源码不能证明生产实例配置的值，也不能证明SSO内部怎样验证账号或授权码。

## 4. 第一个请求之前：本机产生的变量

入口：[account_processor.rs:532](/Users/w/codex_0_2_6/codex-rs/app-server/src/request_processors/account_processor.rs:532) → [server.rs:162](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:162) → [pkce.rs:12](/Users/w/codex_0_2_6/codex-rs/login/src/pkce.rs:12)。

| 变量 | 来源与保存位置 | 后面在哪里用 |
| --- | --- | --- |
| RPC request id | Desktop发起本地请求时使用 | app-server将结果对应到这条RPC；不承担OAuth认证 |
| loginId | app-server生成UUID，放active_login，返回Desktop | 取消/替换登录任务、过滤旧任务、完成通知；不发送给SSO，不等于state |
| client_id | Codex配置/默认应用标识 | new-api查oauth_server_clients；代表应用，不代表员工 |
| outer_state | Codex生成32字节随机值并Base64URL编码；本次登录任务内存 | 经授权页和重定向原样返回；process_request比较回调state与本机原值 |
| code_verifier | Codex生成64字节随机值并Base64URL编码；本次登录任务内存 | 不放浏览器授权URL；第15步由本机直接发送给new-api |
| code_challenge | BASE64URL(SHA256(code_verifier)) | 先放授权URL，后随授权码记录存数据库，换Token时用来校验verifier |
| actual_port | bind_server成功绑定的本机端口 | 组成redirect_uri；默认1455，也存在1457回退分支 |
| redirect_uri | `http://localhost:<actual_port>/auth/callback` | 授权时检查允许列表；换Token时必须与授权码记录完全一致 |
| auth_url | issuer + `/oauth/authorize` + 上述参数 | 返回Desktop交给浏览器导航；不是Token交换请求 |

app-server明确设置 `open_browser: false`，所以这一入口由调用方接收authUrl并打开浏览器。CLI等其他入口可让LoginServer自己打开浏览器。此处验证的是Rust接口行为，未检查当前安装的Electron构建实际使用的打开浏览器函数。

授权请求的关键部分如下，实际还包括originator和若干兼容提示参数：

```text
GET <new-api issuer>/oauth/authorize
  ?response_type=code
  &client_id=<Codex应用ID>
  &redirect_uri=http://localhost:1455/auth/callback
  &scope=openid profile email offline_access api.connectors.read api.connectors.invoke
  &state=<OUTER_STATE>
  &code_challenge=<CHALLENGE>
  &code_challenge_method=S256
```

这里的空格和URL只是排版示意，实际请求由代码做URL编码。`openid`控制ID Token签发，`offline_access`控制refresh token签发。当前URL生成函数没有生成或发送nonce；不能把outer_state说成nonce。

## 5. 内层SSO：把员工身份转换为本地User.Id

路由：[api-router.go:47](/Users/w/ruijie/new-api/router/api-router.go:47)。处理入口：[controller/oauth.go:24](/Users/w/ruijie/new-api/controller/oauth.go:24)、[HandleOAuth:45](/Users/w/ruijie/new-api/controller/oauth.go:45)。

`GenerateOAuthCode`名字虽然有Code，但它生成的是内层state，返回字段是data，并非SSO授权码。

```text
浏览器请求state
→ new-api生成inner_state
→ session.Set("oauth_state", inner_state)
→ session.Save()
→ Set-Cookie: session=<已编码并认证的数据>
→ JSON data返回inner_state给前端构造SSO URL
```

`HandleOAuth`执行：读provider slug → `c.Query("state")`与Cookie Session里的oauth_state比较 → `c.Query("code")` → `provider.ExchangeToken` → `provider.GetUserInfo` → `findOrCreateOAuthUser` → `setupLogin`。Session已有username时进入绑定分支；匿名SSO登录进入用户查找逻辑，生产预开通账户通过已有Binding读取User。

这里 `provider`是Go接口，配置为自定义锐捷provider时实际调用 [GenericOAuthProvider.ExchangeToken](/Users/w/ruijie/new-api/oauth/generic.go:90) 与 [GetUserInfo](/Users/w/ruijie/new-api/oauth/generic.go:202)。由Go HTTP客户端直接调用SSO，浏览器不会执行这两次后端请求，也不需要持有SSO access token。客户端secret按配置放表单或HTTP Basic，不能与Codex的public client混为一谈。

| 身份字段 | 谁产生/拥有 | 用途 |
| --- | --- | --- |
| ProviderId | new-api的custom_oauth_providers本地配置行主键 | 标识是哪一个SSO提供方配置；不是SSO员工ID |
| ProviderUserID | SSO userinfo中，由UserIdField配置指定的字段 | 在该提供方中的稳定员工标识 |
| UserOAuthBinding.UserId | new-api绑定表 | 把外部员工身份映射到本地用户 |
| User.Id | new-api users表主键 | 登录Session、OAuth授权记录、API Token和钱包计费共同关联的用户 |

映射是 `(ProviderId, ProviderUserID) → user_oauth_bindings.user_id → users.id`，见 [GetUserByOAuthBinding](/Users/w/ruijie/new-api/model/user_oauth_binding.go:41)。生产主路径读取申请阶段已创建的User和Binding，并检查本地账户状态。源码另有“无绑定且允许注册”的备用分支，在 `controller/oauth.go:288` 的事务中创建User和Binding；这不是已确认的申请预开通事务，不能用它代替申请服务的实现证据。OA员工ID与new-api的User.Id是不同标识，通过绑定表关联。

`setupLogin`见 [controller/user.go:144](/Users/w/ruijie/new-api/controller/user.go:144)：写入id/username/role/status/group，Save后返回用户信息。前端的用户store与localStorage uid用于页面状态；后端授权不信任前端自己填写的uid，而是读取受保护的Session。

## 6. Cookie、SessionSecret和gin.Context分别是什么

[main.go:195](/Users/w/ruijie/new-api/main.go:195)使用 `cookie.NewStore([]byte(common.SessionSecret))` 并安装 `sessions.Sessions("session", store)`。

- Cookie是浏览器保存并随符合域名、路径等条件的请求发送的数据。
- Session是业务代码操作的状态对象。当前CookieStore把Session数据编码、认证后放进Cookie，并不是MySQL/Redis中的服务端Session行。
- SessionSecret是服务端配置的认证密钥，用于Cookie防篡改；不为每个用户生成，不发给浏览器，不是SSO client_secret，也不是OAuth JWT的RSA签名私钥。
- 当前只传一个Cookie认证key，不应声称Cookie内容已额外加密。
- `*gin.Context`属于单次HTTP请求；`sessions.Default(c)`借助中间件恢复跨请求Cookie状态。OAuth Service里的 `c.Request.Context()`主要传递取消/超时，和Session是不同概念。

SSO Cookie归SSO域；new-api Cookie归new-api域。SSO已登录不自动等于new-api已有Session。Cookie设置包括HttpOnly、30天MaxAge、SameSite Strict，Secure由配置决定。真实跨站重定向是否按预期携带Cookie仍需浏览器验证；本实现先回到同站SPA，再由SPA请求 `/api/oauth/ruijie`。

## 7. 外层授权：new-api保存了什么约束

根路由注册在 [controller/oauth_server.go:93](/Users/w/ruijie/new-api/controller/oauth_server.go:93)。它没有套普通API TokenAuth来决定谁登录，而由 [OAuthAuthorize](/Users/w/ruijie/new-api/controller/oauth_server.go:129)读取Session userID。

GET默认直接执行 `renderOAuthAuthorize`返回HTML；另有SPA授权页面可以读取 `/api/oauth/authorize/meta`，该meta接口不签发授权码。

`oauthAuthorizationRequestFromRequest`从GET query或POST form读取client_id、redirect_uri、scope、challenge、method、nonce，UserID则从Session传入。POST批准后先获取普通codex-token，再创建外层授权码。

| 数据 | 保存内容 | 消费/校验点 |
| --- | --- | --- |
| 普通codex-token | tokens表：UserId、Name=codex-token、Key、状态和额度属性 | 后续模型TokenAuth验证Key并取得Token.UserId |
| 外层授权码codex_code | oauth_server_authorization_codes：code hash、UserId、ClientId、RedirectURI、Scopes、challenge/method、有效期、ConsumedAt | ExchangeAuthorizationCode查hash，再逐项检查 |
| 用户授权许可 | oauth_server_user_grants中的user/client/scopes等 | 查看与撤销授权，以及后续许可管理 |
| outer_state | 授权页面隐藏字段、POST表单、callback URL中传递 | new-api不拿它做inner_state比较，也不把它存为授权码记录的state；Codex回调校验 |

[CreateAuthorizationCode](/Users/w/ruijie/new-api/service/oauthserver/service.go:288)只保存授权码hash，明文通过302给浏览器带到本机。默认有效期为10分钟（可配置）。`GetOrCreateNamedUserToken`会复用已有命名Token；新建时普通Token默认不过期且无Token自身额度上限，这不表示用户钱包免费。

## 8. 回调与换Token：谁验证什么

[process_request](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:320)在 `/auth/callback` 分支依次做：

1. 回调state与本机outer_state比较；不等返回400。
2. 处理OAuth error，检查code非空。
3. 如果有codex-token，尝试写环境变量和provider配置。失败只记录警告，继续登录。
4. 本机直接请求new-api `/oauth/token`，携带授权码和最初保存的verifier。

```text
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<CODEX_CODE>
&client_id=<Codex应用ID>
&redirect_uri=<与授权时相同的localhost回调地址>
&code_verifier=<本机最初生成的VERIFIER>
```

new-api的 [OAuthToken](/Users/w/ruijie/new-api/controller/oauth_server.go:174)解析表单或JSON并按grant_type分派；[ExchangeAuthorizationCode](/Users/w/ruijie/new-api/service/oauthserver/service.go:325)在事务内检查：

- client是否存在且启用；默认Codex是public client，不要求client_secret。
- 授权码hash是否命中，是否已消费或过期。
- code记录的client_id和redirect_uri是否与本次请求一致。
- [verifyPKCE](/Users/w/ruijie/new-api/service/oauthserver/service.go:949)计算 `BASE64URL(SHA256(verifier))`，是否等于授权时保存的challenge。
- 授权码关联的User是否仍启用。
- 用 `WHERE id=? AND consumed_at IS NULL`条件更新消费标记，并要求 `RowsAffected == 1`，防止同一码重复兑换。
- 在同一事务中签发/记录OAuth Token，失败时事务回滚。

因此state解决“这个回调是否对应我发起的登录”，PKCE解决“兑换码的一方是否持有最初生成的秘密”，UserId解决“这份授权属于哪个本地用户”。三个检查互不替代。

## 9. 返回的凭据、JWT字段与保存位置

| 数据 | 产生者/保存处 | 后续用途与实际验证 |
| --- | --- | --- |
| SSO access token | SSO签发；new-api请求内的OAuthToken对象 | 仅用于SSO userinfo，当前登录链未持久化它 |
| Codex OAuth access_token | new-api RS256签发；服务端保存hash及UserId/ClientId/有效期/撤销状态；Codex保存明文凭据 | 携Bearer访问支持的OAuth/账户接口；new-api UserInfo/Relay认证通过token hash匹配数据库并检查状态、用户、客户端及相关scope |
| Codex id_token | new-api在openid scope下签发；Codex凭据存储 | Codex解析账户展示信息、account_id和可选workspace约束；当前解析函数不能等同于完整验签 |
| Codex refresh_token | new-api在offline_access scope下生成随机值；服务端存hash与轮换链，Codex存明文 | 后续refresh_token grant，new-api检查客户端/有效期/撤销状态并轮换 |
| 普通codex-token | new-api tokens表；Codex进程环境与provider配置 | provider Bearer优先用于模型网关；TokenAuth查询普通Token归属 |
| JWT sub | new-api把User.Id转成字符串 | 表示本地用户身份，不是SSO原始员工标识 |
| JWT iss/aud/exp/jti/kid | issuer、client_id、有效期、独立随机JWT ID、签名key id | 描述签发者/接收应用/有效期/Token标识/公钥选择；这些字段存在不代表每个消费者都执行同样的验证 |
| account_id | new-api生成Codex兼容账户标识，Codex从ID Token claims提取 | 本地账户展示和相关接口上下文，不是新的钱包归属主键 |
| last_refresh | Codex保存凭据时写当前时间 | 本地凭据刷新管理；不是套餐重置日期 |

签发见 [service.go:709](/Users/w/ruijie/new-api/service/oauthserver/service.go:709)、[signJWT:771](/Users/w/ruijie/new-api/service/oauthserver/service.go:771)。Codex保存见 [persist_tokens_async](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:1100)。文件/钥匙串等后端由配置选择，不能只凭结构名AuthDotJson断言当前机器一定写入auth.json。

当前Codex还调用 [obtain_api_key](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:1350)，用ID Token再次POST `/oauth/token`，grant_type为 `urn:ietf:params:oauth:grant-type:token-exchange`。new-api只支持authorization_code和refresh_token，因此返回400 unsupported_grant_type。调用方 `.await.ok()`把失败变成None，再继续保存OAuth凭据。当前模型接入不靠这次额外交换成功。

服务端虽然提供discovery/JWKS，但这条Codex登录主链直接拼端点并解析ID Token claims；没有证据表明它在登录时额外请求JWKS做完整ID Token签名、issuer、audience、nonce校验。new-api自身接收OAuth access token的路径也应按具体源码解释：例如 [AuthenticateRelayAccessToken](/Users/w/ruijie/new-api/service/oauthserver/service.go:533)使用服务端Token hash记录来认证，不能泛称“所有请求都是JWT离线验签”。

## 10. 登录完成后为何能请求模型

`persist_codex_token_setup`设置进程中的 `RUIJIE_UNIAPI_KEY`；macOS另尝试launchctl setenv。配置写入选择 `model_provider = "ruijie-uniapi"`，新增provider时写入base_url/env_key/wire_api/api_key。

已有provider配置是特殊分支：若已经存在api_key，`write_ruijie_uniapi_api_key`保留旧值，不覆盖。见 [server.rs:850](/Users/w/codex_0_2_6/codex-rs/login/src/server.rs:850)。所以“回调拿到新Token”“当前进程环境已更新”“磁盘配置已替换旧Token”不是同一事实。

认证选择见 [model-provider/auth.rs:180](/Users/w/codex_0_2_6/codex-rs/model-provider/src/auth.rs:180)：优先使用provider的API Key/Bearer，再回退到账户认证。Header写入见 [bearer_auth_provider.rs:31](/Users/w/codex_0_2_6/codex-rs/model-provider/src/bearer_auth_provider.rs:31)。在新配置成功生效的主路径中：

```text
Codex POST <provider base_url>/responses
Authorization: Bearer <codex-token>
JSON: model、input、tools、stream等模型请求字段
```

new-api链路：[router/relay-router.go:69](/Users/w/ruijie/new-api/router/relay-router.go:69) → [TokenAuth](/Users/w/ruijie/new-api/middleware/auth.go:319) → ModelRequestRateLimit/ToolExtractor → [Distribute](/Users/w/ruijie/new-api/middleware/distributor.go:32) → [controller.Relay](/Users/w/ruijie/new-api/controller/relay.go:68) → [ResponsesHelper](/Users/w/ruijie/new-api/relay/responses_handler.go:23)。

| 本次模型请求的新状态 | 产生/使用位置 |
| --- | --- |
| Request ID | 请求中间件，关联当前HTTP日志；不是登录state或loginId |
| user_id、token_id、token_auth_type、group/模型限制 | TokenAuth验证凭据后写gin.Context，供限流/分发/计费使用；身份来自服务端Token记录 |
| 渠道ID、base URL、上游渠道Key | Distribute选择渠道并写Context/RelayInfo；供Adaptor发上游请求 |
| RelayInfo.UserId/TokenId等 | GenRelayInfo汇集本次请求信息；不是写一个新的浏览器Session |
| 预估Token、价格、预扣额度、BillingSession | Controller估价后PreConsumeBilling，供结算/退款 |
| 实际Usage、actualQuota | Adaptor处理响应，PostTextConsumeQuota/SettleBilling结算并记录消费 |

上游请求使用渠道Key，不能把Codex的网关Token直接当供应商Key。费用最终归属经过绑定得到的User.Id对应的钱包或订阅。`UnlimitedQuota`仅表示API Token自身不限额，不免除钱包/订阅扣费。

SSE可以在接收上游时逐步转给Codex，最终Usage结算发生在处理末尾；图3不宜画成所有响应字节都等结算完成才开始发送。具体渠道协议转换由所选Adaptor与配置决定。

此外TokenAuth也支持OAuth access token，它走独立凭据类型与数据库命名空间。OAuth access-token行的Id不能当普通tokens行的Id，OAuth请求用认证得到的UserId归属计费。

## 11. 本轮确认的实际分支和待运行验证项

1. SSO完成后恢复授权URL：`use-ruijie-oauth-login.ts:50`只传provider，`use-oauth-login.ts:225`因此可能清掉已保存redirect；回调页默认去Dashboard。需要实际复现入口与页面导航，不能宣称流程已自动闭环。
2. 端口兼容：Codex有1457回退；new-api默认OAuth client允许列表只列1455。已有数据库client可能另有配置，本次未读取生产行。
3. 凭据保存次序：codex-token配置先写，OAuth换Token后写；前一步失败继续，后一步失败可能留下配置。所以Desktop成功状态与模型可用性需要分别验证。
4. 既有provider api_key保留旧值，换账号或重启后的实际生效Token需单独观察；本次未操作用户配置。
5. 刷新/撤销：当前 `login/src/auth/manager.rs:191`默认是HTTP地址，初次登录issuer为HTTPS；有环境覆盖入口，尚未核对实际运行值。刷新发送JSON，new-api同时支持JSON和表单。
6. 两层state不是单次消费Token：外层state随本机登录任务结束失效；内层state处理代码主要比较值，当前路径未显示消费后删除。外层授权码的一次性由数据库ConsumedAt机制保障。
7. 回调URL含codex-token，因此观察Network、代理日志或浏览器历史时不要复制完整URL。当前Generic OAuth调试代码还可能输出code片段/token响应/userinfo内容，真实运行采集不能直接整段导出这些日志。

## 12. 用源码和测试分析这条链的方法

阅读时每个箭头都记录五项：发送者、HTTP方法/路径、数据来自哪里、接收函数如何取值、校验/持久化以后如何返回。跨请求只能靠明确的Cookie、数据库记录或本机任务状态续接，不能把不同请求的gin.Context当成同一个对象。

建议断点顺序：

1. Codex `run_login_server`：看state/PKCE/redirect_uri字段的存在性；step-over看auth_url生成，不复制值。
2. new-api `GenerateOAuthCode`：看Set与Save前后，理解Cookie写回。
3. `HandleOAuth`：看query与session比较结果；step-into跟踪接口派发到GenericOAuthProvider。
4. `findOrCreateOAuthUser`、`setupLogin`：看User/Binding关联及Session字段；只在本地测试夹具观察具体行。
5. `OAuthAuthorize`、`CreateAuthorizationCode`：看表单到结构体、CodeHash记录和challenge的保存。
6. Codex `process_request`与new-api `ExchangeAuthorizationCode`：先看本机state比较，再看后端PKCE比较和RowsAffected。
7. `TokenAuth`：登录结束后另发一条模型请求，确认凭据类型、用户归属和渠道；不能从登录成功推断这一步成功。

本轮实际执行：

```bash
GOCACHE=/private/tmp/new-api-learning-gocache go test ./service/oauthserver ./controller -run 'Test(AuthorizationCode|ExpiredAuthorizationCode|PKCEMismatch|RefreshTokenRotation|OAuthAuthorize|OAuthToken)' -count=1
```

结果：Service包ok（1.253s），Controller包ok（1.217s）。关键行为覆盖包括授权页Session门禁、approve后的code/state/codex-token、已有Token复用、拒绝授权/非法client/redirect/scope、授权码重复消费与过期、PKCE不匹配、刷新轮换和JSON刷新请求。

这些测试采用本地夹具数据库和Gin httptest。它们不证明真实锐捷SSO配置、浏览器Cookie/跳转、Desktop本机回调、JWT客户端完整验证、Rust编译或上游推理/计费成功。本次没有修改登录实现，也没有标记任何学习项为已掌握。
