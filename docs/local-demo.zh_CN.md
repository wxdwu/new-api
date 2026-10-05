# MySQL 本地演示环境

这套环境用于在本机浏览默认前端和核心运维页面。它不会调用真实模型，不需要真实 API Key、支付账号或 OAuth 配置。

## 数据组件

| 组件 | 本地配置 | 用途 |
|---|---|---|
| 主业务数据库 | MySQL 8.2 | 必需；保存用户、令牌、渠道、模型、设置和统计数据 |
| Redis | Redis 7 | 可选能力；本演示环境启用，用于缓存、限流和实例同步 |
| 日志数据库 | 复用 MySQL | 不启用独立 SQL 日志库或 ClickHouse |

项目的业务数据库代码同时支持 SQLite、MySQL 5.7.8 及以上版本、PostgreSQL 9.6 及以上版本。本地演示统一使用 MySQL 8.2，业务数据和日志数据都写入 `new-api` 数据库。

## 启动前准备

1. 安装并打开 Docker Desktop，等待 Docker 服务进入可用状态。
2. 确认本机的 `3300` 和 `33307` 端口未被占用。应用端口可通过 `NEW_API_LOCAL_PORT` 修改，MySQL 端口可通过 `NEW_API_LOCAL_MYSQL_PORT` 修改。
3. 首次构建需要联网下载 Docker 镜像、Go 模块和前端依赖，完成后运行演示不需要任何真实业务凭据。

## 一键启动

在仓库根目录运行：

```bash
./scripts/local-demo.sh bootstrap
```

脚本会依次启动 MySQL 和 Redis、执行原有数据库迁移、写入虚拟数据、构建默认前端和应用，并等待健康检查通过。

完成后打开：

- 登录地址：`http://127.0.0.1:3300/sign-in`
- 登录方式：展开“用户名和密码登录”
- 用户名：`demo-root`
- 密码：`LocalDemo123!`

以上密码只能用于本机演示。首次初始化前可用环境变量覆盖：

```bash
LOCAL_DEMO_ROOT_PASSWORD='YourLocalPassword123!' ./scripts/local-demo.sh bootstrap
```

MySQL 默认连接信息：

- 地址：`127.0.0.1`
- 端口：`33307`
- 数据库：`new-api`
- 用户名：`root`
- 密码：`LocalDemoMySQL123!`

可以使用 Navicat、DBeaver 等客户端直接连接。也可以从命令行进入：

```bash
docker compose --project-name new-api-local-demo \
  --file docker-compose.local.yml \
  exec mysql mysql -uroot -p'LocalDemoMySQL123!' new-api
```

首次初始化前可覆盖 MySQL 端口和密码：

```bash
NEW_API_LOCAL_MYSQL_PORT=33308 \
LOCAL_DEMO_MYSQL_PASSWORD='YourLocalMySQL123!' \
./scripts/local-demo.sh bootstrap
```

## 演示数据范围

初始化器创建 4 个本地用户，覆盖超级管理员、管理员、普通用户和禁用用户；同时创建限额、无限额、禁用和过期等状态的令牌。

OpenAI、Anthropic 和 Gemini 三类演示渠道均处于手动禁用状态，使用不可达的本机地址和确定性的假密钥。不要启用或测试这些渠道，它们只用于展示管理页面。

此外还包括：

- 3 个供应商和 4 个模型元数据；
- 禁用的渠道能力关系；
- 最近 7 天的用量、流量和模型性能指标；
- 消费、登录、管理和错误等类型的演示日志；
- 默认前端、密码登录、数据看板和消费日志所需的系统设置。

初始化器不创建兑换码、订阅、支付订单、OAuth 绑定或模型回复。

## 常用命令

```bash
# 幂等刷新带固定演示标识的数据，不修改后来手工创建的数据
./scripts/local-demo.sh seed

# 使用 Cookie 会话登录并检查用户、令牌、渠道、模型、日志和统计接口
./scripts/local-demo.sh verify

# 查看容器状态
./scripts/local-demo.sh status

# 停止服务，保留 MySQL、Redis 和应用数据卷
./scripts/local-demo.sh down

# 确认后只删除 new-api-local-demo 这套环境的数据卷，再重新初始化
./scripts/local-demo.sh reset
```

无人值守重置可显式确认：

```bash
./scripts/local-demo.sh reset --yes
```

## 安全与幂等规则

首次执行时，初始化器只接受空用户库；如果数据库已有用户但没有 `LocalDemoSeedVersion` 标记，它会拒绝写入。成功后会记录版本标记。再次执行只更新或重建带固定演示标识的记录，不会清理其他用户后来创建的数据。

Compose 将应用端口和 MySQL 端口绑定到 `127.0.0.1`，不会对局域网暴露；Redis 不暴露到宿主机。`reset` 只作用于 Compose 项目 `new-api-local-demo` 当前声明的数据卷。此前创建的 PostgreSQL 数据卷会保留，不会在本次切换或后续 MySQL 重置时删除。

## 故障排查

- 提示 Docker 服务不可用：打开 Docker Desktop，等待启动完成后重试。
- `3300` 端口已占用：运行 `NEW_API_LOCAL_PORT=3301 ./scripts/local-demo.sh bootstrap`，后续 `verify` 使用相同环境变量。
- `33307` 端口已占用：运行 `NEW_API_LOCAL_MYSQL_PORT=33308 ./scripts/local-demo.sh bootstrap`，数据库客户端也改用同一端口。
- 首次构建下载超时：确认 Docker Desktop 的网络可用后重新执行 `bootstrap`，已完成的构建层会被复用。
- 登录密码被覆盖：后续执行 `seed` 和 `verify` 时，继续传入初始化时使用的 `LOCAL_DEMO_ROOT_PASSWORD`。
