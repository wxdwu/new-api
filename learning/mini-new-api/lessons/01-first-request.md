# 第 1 课：自己建立模块，跑通一个 HTTP 接口

状态：待开始。本文是任务卡，命令和预期结果尚未执行。

本课只解决一个问题：**我写的 Go 文件怎样变成监听端口、能返回 JSON 的服务？**

## 1. 本课完成后要能解释

- `go.mod`、`package main`、`func main()` 分别做什么。
- 是谁创建 Gin Engine，谁注册路由，谁监听端口。
- Handler 为什么接收 `*gin.Context`，谁调用它。
- `go run .` 的点指哪个目录，和 new-api 根项目有什么关系。

只做一个 `GET /api/status`。请求成功时 HTTP 状态为 200，JSON Body 是 `{"success":true,"message":"mini new-api is running"}`。这只能证明 HTTP 能应答。

## 2. 先预测这条链

```text
你在终端 A 执行 go run .
→ Go 构建并运行当前 main 包
→ main 创建 Gin Engine、注册 GET 路由、监听回环地址

你在终端 B 执行 curl
→ HTTP 请求到达 Go 进程
→ Gin 匹配方法和路径
→ Gin 调用 Handler，传入本次请求的 Context
→ Handler 写 JSON
→ curl 展示响应
```

先想两个问题：注册路由时会立即执行 Handler 吗？终端 A 一直没有回到命令提示符，是否表示程序卡死？

## 3. 由你执行的准备步骤

先检查 `go version`。如果报错，把错误贴给助手，本课再定位环境；不用先重装一整套开发工具。

下面的目录是新的练习模块。**请确认进入 app 后再执行 go mod init。**

```bash
mkdir -p /Users/w/ruijie/new-api/learning/mini-new-api/app
cd /Users/w/ruijie/new-api/learning/mini-new-api/app
pwd
go mod init example.com/mini-new-api
go get github.com/gin-gonic/gin@v1.9.1
```

首次本机对照练习暂按当前仓库的 Gin v1.9.1 锁定，方便对照源码；这不是推荐生产使用旧版本。`example.com/mini-new-api` 是本地练习 module 名，不会帮你创建远端仓库。依赖下载会访问网络，失败时保留具体错误再排查。

## 4. 你创建 main.go 并补全

把下面的骨架复制到 `app/main.go`，然后填空。`___` 是题目占位，未补完不能编译。助手本次没有创建这个文件。

```go
package main

import (
    "log"
    "net/http"

    "github.com/gin-gonic/gin"
)

func main() {
    r := ___ // 1. 创建 Gin Engine
    r.Use(gin.Recovery())

    r.___("/api/status", func(c *gin.Context) { // 2. 注册 HTTP 方法
        c.___(http.StatusOK, gin.H{             // 3. 写哪种响应
            "success": ___,                    // 4. 布尔值
            "message": "mini new-api is running",
        })
    })

    err := r.___("127.0.0.1:38080") // 5. 开始监听
    if err != nil {
        ___ // 6. 用 log.Fatal 报告启动失败
    }
}
```

提示只给职责：`gin.New` 创建 Engine；Engine 的方法负责注册 HTTP 方法和启动服务；Context 的方法负责写响应。先自己查方法名，把每个填空对应到请求链。

此处的匿名函数是路由回调。可以先把 `*gin.Context` 理解为“Gin 交给 Handler 的本次请求对象指针”，指针和生命周期在后续课里观察。

## 5. 由你运行并采集证据

在终端 A，仍位于 `app/`：

```bash
gofmt -w main.go
go run .
```

`gofmt` 是你主动执行的格式整理命令；如果出现语法错误，先确认占位已填完。若端口占用，不结束其他不明进程，改成本机另一个空闲端口并同步 curl 地址。

在终端 B：

```bash
curl -i http://127.0.0.1:38080/api/status
curl -i http://127.0.0.1:38080/api/missing
```

预期第一条是 200 和上述 JSON，第二条是 404。记录实际值；JSON 字段顺序不影响含义。随后在终端 A 按 Ctrl+C，再请求第一条，观察连接失败。

本课不用增加仅验证固定字符串的测试文件。中间件顺序和输入验证等有实际行为时开始写测试；本课先看清真实启动和 HTTP 请求。

## 6. 回看 new-api 的相同位置

- [main.go:177](/Users/w/ruijie/new-api/main.go:177)：同样先创建 Gin Engine。
- [main.go:209](/Users/w/ruijie/new-api/main.go:209)：大项目把注册动作交给 `router.SetRouter`。
- [router/main.go:16](/Users/w/ruijie/new-api/router/main.go:16)：注册不同业务路由。
- [main.go:220](/Users/w/ruijie/new-api/main.go:220)：把 Gin 交给 `http.Server`，后面还有信号与优雅退出处理。

练习里的 `Run` 用来先理解监听；new-api 显式创建 `http.Server` 用于控制生命周期。只比较当前这几个动作，不追读全部初始化和后台任务。

## 7. 本课反馈与进入下一课的条件

把你填完的 `main.go`、实际响应或错误，以及下面三句话的回答发给助手：

1. “一个 module、一个 package、一个 main 函数之间的关系是……”
2. “当我请求 `/api/status` 时，是……调用 Handler，并传入……”
3. “路由注册发生在……，Handler 执行发生在……”

助手会根据你的答案继续解释和评审，不直接改文件。你明确确认“搞懂了”后，记录本课掌握；下一课再比较构建目标与启动装配。
