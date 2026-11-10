# Replatform × Keycloak × HKU GreenU

独立的本地 PoC，使用 FastAPI 和 Keycloak Java 自定义 QR grant：

```text
RVM → FastAPI /auth/qr → Keycloak QR grant → GreenU member API
                          ↓ 验证、映射用户、签发 Token
RVM ← Token + 脱敏姓名/余额
RVM → FastAPI /transactions → 验证 Token → GreenU deposit API
```

## 本地启动（模拟 GreenU）

需要 Docker Desktop。已生成 `.env`，其中本地密码随机生成，真实 GreenU 凭证尚未填入。`.env` 已加入 `.gitignore`。

```bash
cd /Users/greenai/Documents/project/keycloak-test
docker compose --profile mock up -d --build
python3 scripts/smoke.py
```

第一次启动需要等待 Keycloak 完成数据库初始化、provider 构建和 realm 导入。如果 smoke 返回 503，稍后重试。

- 后端 Swagger：http://localhost:8000/docs
- Keycloak 管理台：http://localhost:8080/admin/ （账号及密码见 `.env`）
- Keycloak 固定版本：26.8.2；Java 21；扩充属于内部 SPI，升级时必须重新编译并运行端到端验证。
- PostgreSQL 与 SQLite 账本使用 named volume 保存。`docker compose down` 停止服务但保留数据。
- `docker compose down -v` **删除本 PoC 的身份和交易数据**，仅需重新初始化时使用。

## 切换真实 HKU GreenU

编辑 `.env`：

```dotenv
GREENU_BASE_URL=https://<HKU提供的主机及基础路径>
GREENU_API_KEY=<HKU提供的API key>
GREENU_ACCESS_CODE=<当前有效的32位十六进制二维码凭证>
GREENU_MERCHANT=GreenAI
RVM_BIN_ID=<HKU认可的回收机IMEI>
```

`GREENU_BASE_URL` 不要包含 `/recycle/member`，适配器会自动追加；真实平台要求 HTTPS。
`GREENU_ACCESS_CODE` 仅由 smoke 脚本读取，后端登录接口始终要求请求携带 code，不会以环境变量绕过认证。不要把动态 QR code 当作固定登录凭证。

```bash
docker compose stop greenu-mock
docker compose up -d --build keycloak backend
python3 scripts/smoke.py
```

smoke 只做会员验证和 `/auth/me`，**不会提交回收交易或增加积分**。
真实 member 验证是否会消耗 accessCode，需要向 HKU 确认。

## Keycloak 预置配置

`keycloak/import/replatform-realm.json` 在新数据库首次启动时自动导入：

| 项目 | 配置 |
|---|---|
| Realm | replatform |
| 认证 client | rvm-auth-backend，confidential，client-secret |
| Browser / Implicit / Direct Access Grants | 关闭 |
| Service accounts | 关闭 |
| 自定义 grant | urn:greenai:params:oauth:grant-type:qr |
| 客户端允许标记 | greenu.qr.enabled=true，greenu.tenant=hku |
| Token audience | replatform-api |
| Access Token 生命周期 | 180 秒 |
| Refresh Token | 不签发；需要重新扫码 |
| 身份 | sub=Keycloak内部用户ID，tenant=hku，identity_provider=greenu |
| 外部身份字段 | external_member_id=GreenU memberID |

Keycloak 管理台没有 GreenU Identity Provider 配置：这里使用自定义 OAuth2GrantType provider，而不是把 REST API 当成 OIDC 提供方，也没有把 code 塞进密码字段。

仅允许启用该属性的 confidential client 使用扫码 grant。后端掌握 client secret；RVM 使用独立 `X-RVM-API-Key`。本 PoC 是单机构、单回收机配置，`binID` 来自服务端环境变量。多个设备时应使用设备注册表和每台设备独立凭证，按设备选择 tenant/binID，而不是信任请求体。

首次成功扫码创建 `hku.greenu.<memberID>` 用户，保存身份映射。不会保存 accessCode；遮罩姓名、余额仅随登录响应返回，不写入 Token。余额由 GreenU 维护。禁用 Keycloak 用户后不允许再次扫码，但已经签发的自包含 Token 最长仍可使用至过期（180 秒）；本 PoC 不提供提前撤销机制或 refresh。RVM 应在交易结束/超时后清除当前 Token。

Realm import **不会覆盖已存在的 realm**。修改 `.env` 中的 client secret 后，需要同步在管理台更新 client 凭证；仅重启不会重新导入。生产中应以部署流程管理该配置。

## RVM API

### 1. 扫码登录

```http
POST /auth/qr
X-RVM-API-Key: <RVM_API_KEY>
Content-Type: application/json

{"accessCode":"0123456789ABCDEF0123456789ABCDEF"}
```

```json
{"accessToken":"...","expiresIn":180,"tokenType":"Bearer","member":{"maskedInfo":"C*** T** M**","balance":386}}
```

无效凭证返回 401；上游 API key 配置错误、上游异常等返回 503。请求格式错误返回 422。上游原始错误不向 RVM 暴露。

### 2. 验证当前身份

```http
GET /auth/me
X-RVM-API-Key: <RVM_API_KEY>
Authorization: Bearer <accessToken>
```

后端通过 JWKS 校验 RS256 签名、issuer、audience、有效期和必要身份字段。内部请求地址与外部 issuer 分开配置，避免 Docker 主机名导致 issuer 不匹配。

### 3. 回收交易（会增加真实积分，仅人工执行）

```http
POST /transactions
X-RVM-API-Key: <RVM_API_KEY>
Authorization: Bearer <accessToken>
Idempotency-Key: <每笔交易唯一且重试时不变的ID>
Content-Type: application/json

{"depositedItems":[{"recyclableType":"Plastic Bottles","quantity":2}]}
```

后端从可信 Token 取得 memberID，从设备配置取得 binID，再调用：

```http
POST {GREENU_BASE_URL}/recycle/member/{memberID}/deposit
api-key: <GREENU_API_KEY>
Content-Type: application/json

{"merchant":"GreenAI","binID":"868618051694099","depositType":"quantity","depositedItems":[{"recyclableType":"Plastic Bottles","quantity":2}]}
```

GreenU 计算积分，后端返回其 `pointsEarned`、`memberBalanceUpdated` 等结果；回收机不能自行提交积分或 memberID。

SQLite 账本在调用前记录交易，同 key 的成功请求返回已缓存结果；同 key 不同内容返回 409。逾时、未知结果、已拒绝交易都不会自动重发。结果不明时不要更换 key 重试，应先向 GreenU 对账。本地去重只覆盖使用相同 key 的请求，不能取代上游幂等支持，也不防止调用方换 key 重复提交。此 PoC 不提供对账/人工恢复接口。

Mock 积分为数量求和，仅验证接口链路，不代表 HKU 正式积分规则；Mock 余额重启会重置。

## 验证

后端单元测试（模拟 HTTP，不调用真实 GreenU）：

```bash
docker compose run --rm --no-deps --user root -v "$PWD/backend/tests:/tests:ro" backend sh -c 'pip install pytest==9.0.2 && python -m pytest /tests -q -p no:cacheprovider'
```

端到端认证验证：`python3 scripts/smoke.py`。完整模拟验证：`python3 scripts/verify_mock.py`（拒绝非本地 mock 配置，包含模拟交易）。完整验证结果见 `VALIDATION.md`。

## 对接前仍需确认

- 规范说 code 是32位十六进制，原始示例却只有16位；本实现按32位校验。
- 原示例 `memberMaskedInfo` 使用逗号，应为 JSON 冒号；请求体尾随逗号也需去除。
- accessCode 有效期、能否重复使用、验证是否消耗凭证。
- GreenU deposit 的交易去重和结果查询方式。
- recyclableType 完整枚举、binID 注册方式、实际 URL 和 API key。

## 部署边界

这是本机 PoC，Keycloak 使用 start-dev、HTTP 和 sslRequired=none，仅绑定 localhost。上线前应使用正式域名/HTTPS、production mode、机构隔离策略和独立设备身份，并升级与验证依赖。不要把本地开发配置直接暴露公网。

新增 OnePass 时，在自定义 grant 的可信 client 配置中增加 provider 路由，并实现独立适配器；此版本只实际实现 GreenU，不声称已支持 OnePass。

官方参考：
- https://www.keycloak.org/docs/latest/server_development/
- https://www.keycloak.org/securing-apps/oidc-layers
