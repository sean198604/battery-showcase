# battery-showcase · 扫码图文展示平台

客人扫二维码 → 打开手机页面 → 看产品图文和参数。业务员在后台改文字、传图片、发布、取二维码。

线上地址：`https://battery.seans.cc.cd/admin/`（后台）、`https://battery.seans.cc.cd/p/<标识>`（客人页面）

## 它做什么

| 能力 | 说明 |
|---|---|
| 内容存放 |  SQLite 存页面与文本块，图片文件存 `storage/`，原图和手机压缩版分开 |
| 后台编辑 | 标题、副标题、页眉类目小字、页脚说明；正文按「文本 / 小标题 / 图片 / 参数表 / 提示框 / 分隔线」分块，可上下调顺序，支持 `**加粗**`、`- 列表`、`## 小标题`、`[文字](https://链接)` |
| 页面生成 | 前台 HTML 由服务端直出，不依赖前端框架和 JS，手机首次打开更快 |
| 显示开关 | 每个内容块可单独「隐藏」：内容仍留在后台和数据库里，只是不在客人页面渲染，随时可恢复显示；复制成新语言时标记一起带过去 |
| 只看图片 | 每个页面可单独勾选「只看图片」：标题、页眉小字、副标题、正文里的文本/小标题/参数表/提示框、页脚说明全都不渲染，页面上只剩图片和图注（封面图仍显示）；取消勾选立刻恢复，内容不删 |
| 草稿/发布 | 草稿只有后台预览能看，发布后二维码才生效；改坏了点「撤下」立刻对客人隐藏 |
| 二维码 | 每页一个，可下载 660px / 1300px / SVG，还能打 A4 打印卡（一张纸 4 份，贴样品、彩盒、外箱、资料册） |
| 多语言 | 复制整页成新语言版本；同一 `分组标识` 的页面在手机上互相切换（切换条在右上角），并自动出上一条 / 下一条 |
| 界面语言 | 「上一条 / 下一条 / 语言」这些界面小词按访客浏览器的 `Accept-Language` 选，覆盖 12 个语种；正文语言仍由页面自己决定 |
| 方向 | 阿拉伯语等自动切右向左排版 |

## 本地跑起来

```bash
cp .env.example .env      # 改管理员账号和口令
docker compose up --build
# 浏览器打开 http://127.0.0.1:7023/admin/
```

没装 Docker 也可以直接跑：

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
SHOWCASE_ADMIN_USER=admin SHOWCASE_ADMIN_PASS=自己的口令 \
  .venv/bin/python -m uvicorn app.main:app --port 7023
```

## 目录

```
app/config.py     路径、账号、上传限制等环境变量
app/db.py         SQLite 建表与查询封装
app/auth.py       scrypt 口令哈希、会话签发、登录失败限流
app/images.py     上传校验、缩略图、孤儿文件清理
app/qr.py         segno 生成 PNG / SVG
app/render.py     前台页面 HTML + 文本排版规则
app/main.py       全部路由（前台 + 后台 API）
static/admin.html 后台单文件页面，无构建步骤
data/ storage/    运行数据，已在 .gitignore 里
```

## 线上部署（东京 ECS）

1. 代码放到 `/home/admin/battery-showcase`，`cp .env.example .env` 并改口令。
2. `docker compose up -d --build`，容器只监听 `127.0.0.1:7023`。
3. Nginx 按运维手册 §6.3 新增 `battery.seans.cc.cd`：先 80 + acme，签 ECDSA 证书，再补 443 反代到 `127.0.0.1:7023`。
4. 验证：`curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7023/api/health` 和公网域名都 200。

内存只有 1.6 GiB，compose 里已写死 `mem_limit: 256m`，不要放开。

## 备份

```bash
sudo cp -a /home/admin/battery-showcase/data   /home/admin/battery-showcase-backups/data.bak.$(date +%Y%m%d%H%M%S)
sudo cp -a /home/admin/battery-showcase/storage /home/admin/battery-showcase-backups/storage.bak.$(date +%Y%m%d%H%M%S)
```

## 已知边界

- 一个管理员账号，够用；要做多业务员再加权限表。
- 图片没有走 CDN，经 Cloudflare 橙云缓存；单张超过 15 MB 会被拒。
- 页面数量软上限 3000，参数表单页最多 200 个内容块。
- 二维码指向的标识一旦改动，旧码立刻失效；改名前先确认旧物料是否还在用。
