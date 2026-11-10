# Replatform × Keycloak × HKU GreenU

## 启动

先启动 Docker Desktop，然后执行：

```bash
cd /Users/greenai/Documents/project/keycloak-test
docker compose --profile mock up -d --build
```

默认使用本地模拟 GreenU。首次启动需等待 Keycloak 初始化完成。

连接真实 HKU 时，修改 `.env` 中的配置：

```dotenv
GREENU_BASE_URL=https://<GreenU基础地址，不含/recycle/member>
GREENU_API_KEY=<API key>
GREENU_ACCESS_CODE=<当前有效的32位十六进制二维码凭证>
RVM_BIN_ID=<回收机IMEI>
```

```bash
docker compose stop greenu-mock
docker compose up -d --build keycloak backend
```

验证登录：`python3 scripts/smoke.py`。脚本读取 `.env` 的二维码凭证，不提交回收交易。

停止服务：`docker compose down`。

## Swagger 和管理台

- [Swagger 接口文档](http://localhost:8000/docs)：可直接调用下面的 API。
- [Keycloak 管理台](http://localhost:8080/admin/)：账号和密码对应 `.env` 的 `KEYCLOAK_ADMIN`、`KEYCLOAK_ADMIN_PASSWORD`。
- 登录管理台后选择 **replatform** Realm，再进入 **Clients → rvm-auth-backend** 或 **Users**。

## API 说明

后端地址：`http://localhost:8000`。以下认证及交易接口均需请求头 `X-RVM-API-Key: <.env中的RVM_API_KEY>`。

### POST /auth/qr — 扫码登录

请求体（JSON）：

```json
{"accessCode":"0123456789ABCDEF0123456789ABCDEF"}
```

成功响应：

```json
{"accessToken":"...","expiresIn":180,"tokenType":"Bearer","member":{"maskedInfo":"C*** T** M**","balance":386}}
```

Token 有效期为 180 秒。无效会员凭证返回 `401`，参数错误返回 `422`，认证服务不可用返回 `503`。

### GET /auth/me — 当前会员身份

额外请求头：`Authorization: Bearer <accessToken>`。

成功响应：

```json
{"userId":"Keycloak内部用户ID","tenant":"hku","provider":"greenu","memberId":"12AB34CD56EF78GH"}
```

### POST /transactions — 提交回收交易

额外请求头：

```http
Authorization: Bearer <accessToken>
Idempotency-Key: <每笔交易唯一的ID，重试时保持不变>
Content-Type: application/json
```

请求体：

```json
{"depositedItems":[{"recyclableType":"Plastic Bottles","quantity":2}]}
```

后端使用 Token 中的会员身份及配置中的回收机编号调用 GreenU，由 GreenU 计算积分。真实环境会增加会员积分。

成功响应示例（积分以 GreenU 返回为准）：

```json
{"message":"Member balance is updated","pointsEarned":3,"memberBalanceUpdated":389}
```

同一交易 ID 的成功重试返回原结果；内容冲突或结果待确认返回 `409`。发生超时或结果不明时，不要更换 ID 重复提交。

### GET /health — 服务存活检查

无需认证，返回 `{"status":"ok"}`。
