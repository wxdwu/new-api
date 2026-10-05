# New API 云端学习环境

这套配置运行四个容器：

```text
浏览器 -> Nginx:80 -> New API:3000 -> MySQL:3306
                                      -> Redis:6379
```

只有 Nginx 的 80 端口映射到宿主机。New API、MySQL 和 Redis 只在 Docker 内部网络中通信。

## 连接服务器

本机已经配置 SSH 别名：

```bash
ssh aliyun-new-api
```

云端部署目录：

```bash
cd /opt/new-api/source/deploy/cloud
```

## 日常操作

查看容器状态：

```bash
docker compose --env-file .env -f docker-compose.yml ps
```

启动服务：

```bash
docker compose --env-file .env -f docker-compose.yml up -d --no-build
```

查看最近日志：

```bash
docker compose --env-file .env -f docker-compose.yml logs --tail=200
```

持续查看 New API 日志：

```bash
docker compose --env-file .env -f docker-compose.yml logs -f --tail=200 new-api
```

重启应用和入口代理：

```bash
docker compose --env-file .env -f docker-compose.yml restart new-api nginx
```

停止并删除容器，但保留数据库和应用数据：

```bash
docker compose --env-file .env -f docker-compose.yml down
```

不要执行 `docker compose down -v`，它会删除 MySQL、Redis 和应用数据卷。

## 从当前代码重新部署

本项目需要在本机为服务器的 `linux/amd64` 平台构建镜像，再上传并导入。这样部署的是当前工作区代码，而不是公共仓库中的同名镜像。

基本流程：

```bash
docker buildx build --platform linux/amd64 -t new-api:cloud --load .
docker save new-api:cloud | gzip > /tmp/new-api-cloud-amd64.tar.gz
scp /tmp/new-api-cloud-amd64.tar.gz aliyun-new-api:/opt/new-api/
ssh aliyun-new-api 'docker load < /opt/new-api/new-api-cloud-amd64.tar.gz'
ssh aliyun-new-api 'cd /opt/new-api/source/deploy/cloud && docker compose --env-file .env -f docker-compose.yml up -d --no-build'
```

如果代码或部署文件发生变化，还需要先把更新后的源码同步到 `/opt/new-api/source`。同步时必须排除 `.env`、私钥和本地数据目录。

## 数据与安全

- 云端密钥只保存在 `/opt/new-api/source/deploy/cloud/.env`，权限应为 `600`，不要提交到 Git。
- 数据保存在 Docker 卷中，重启容器和服务器不会丢失。
- MySQL 和 Redis 没有映射公网端口。
- 阿里云安全组只需放行 SSH 22 和网页入口 80；学习完成后可关闭 80 或停止实例。
- 当前 Nginx 只允许配置文件中指定的公网 IP。网络变化后，需要更新 `nginx.conf` 的 `allow` 地址并重新加载 Nginx。
- 当前使用 HTTP。后续绑定域名并配置 HTTPS 后，再启用安全 Cookie。

## 首次使用

安全组放行 80 且当前公网 IP 与 Nginx 白名单一致后，打开服务器公网地址。页面会引导创建第一个管理员账号。管理员密码应由使用者在页面中自行设置，不要写入部署文件或聊天记录。
