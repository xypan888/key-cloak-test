# 验证记录

日期：2026-11-09（Asia/Hong_Kong）。

- Keycloak 26.8.2 / Java 21 自定义 grant：Maven 编译打包成功。
- Realm 导入成功，已在 PostgreSQL 中初始化。
- FastAPI 后端：17 项测试通过。
- 测试覆盖：设备凭证、输入校验、上游故障分类、异常响应、过期 Token、错误 issuer/audience/client/tenant、交易参数来源、幂等与逾时不重试。
- 端到端：使用实际 Keycloak 容器及本地 GreenU mock，通过扫码、会员映射、签名 Token 签发和后端 JWKS 验证。
- 端到端：无效二维码、错误设备 key、伪造签名被拒绝；重复扫码使用同一内部用户。
- 模拟 deposit 与同 key 重复提交通过；冲突内容返回 409。
- 未提供真实 GreenU URL/API key，未进行真实 HKU 联调或真实积分操作。
- 测试存在一条 Starlette TestClient 对 httpx 的弃用提示，不影响本次结果。

复现认证检查：`python3 scripts/smoke.py`（读取 .env，不提交 deposit）。

复现完整模拟检查：`python3 scripts/verify_mock.py`（仅允许 .env 配置为 greenu-mock，包含模拟 deposit）。

配置为真实 GreenU 后，应重新执行认证联调；真实 deposit 必须在确认测试账户、设备及幂等规则后人工验证。
