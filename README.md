# 港口潮汐通航窗口 API

基于 **Python 3.11 + FastAPI + SQLite** 的潮汐通航辅助服务。录入港口的潮高预报点与航道基准水深后，船舶提交吃水、安全富余和所需通航时长，服务按线性插值计算全部可出发时段及最早出发时刻。

## 计算规则

1. **线性插值**：相邻潮高预报点之间，潮高按时间线性插值。
2. **只在预报覆盖时段内计算**：即 `[第一个预报点, 最后一个预报点]`，绝不外推；落在覆盖边界的达标端点照常纳入。
3. **达标判定**：实际水深 = 潮高 + 航道基准水深；当
   `实际水深 ≥ 吃水 + 安全富余` 时该时刻可通航（**端点恰好达标也纳入**）。
4. **连续窗口合并**：跨多个插值线段、彼此相接（含端点重合）的达标时段合并为一个连续窗口。
5. **可出发时段**：对每个连续窗口 `[ws, we]`，
   - 可出发时段 = `[we − 通航时长, we]`（在 we 时刻恰好出发也能在窗口内完成通航）；
   - 窗口时长 `< 通航时长` 的窗口直接舍弃（恰好相等时保留）。
6. **返回全部可出发时段**，并给出 `earliest_departure`（第一个窗口的可出发起点，无窗口为 `null`）。
7. **预报更正即时生效**：预报点整组替换在单事务内完成（`DELETE + INSERT`），每次查询都实时读取库内最新数据重算，无任何结果缓存。
8. 时间统一按 **UTC** 处理：录入无时区时间戳按 UTC 解释，带时区的自动转换为 UTC。

## 一条命令启动（Docker Compose）

```bash
docker compose up --build -d
```

该命令一次性完成：**构建镜像 → 安装依赖 → 初始化数据库（建表）→ 写入演示数据 → 启动服务**。容器启动入口 `entrypoint.sh` 幂等，可重复执行。

停止 / 查看日志：

```bash
docker compose logs -f
docker compose down            # 停止并删除容器 (数据库卷保留)
docker compose down -v         # 同时清空数据库卷
```

## 访问地址与端口

| 项目 | 地址 |
| --- | --- |
| 服务地址 | `http://localhost:8000` |
| 健康检查 | `GET http://localhost:8000/health` |
| Swagger UI（交互式文档） | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| OpenAPI Schema | `http://localhost:8000/openapi.json` |

容器内监听 `0.0.0.0:8000`；如需改宿主机端口，编辑 `docker-compose.yml` 的 `ports`（如 `"18000:8000"`）。

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_PATH` | `/data/tides.db` | SQLite 数据库文件路径，Compose 中挂在命名卷 `tide-data` 上持久化 |
| `SEED_DEMO` | `1` | 启动时是否写入演示港口「示例港」（基准水深 10 m + 25 个整点潮高）；设为 `0` 则空库启动 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8000` | 监听端口（同时影响容器内端口与健康检查） |

所有潮高、基准水深、吃水、富余的单位均为 **米**，且必须使用同一潮高基准面（如理论最低潮面）。

## API 一览

### 1. 创建港口

```bash
curl -X POST http://localhost:8000/ports \
  -H 'Content-Type: application/json' \
  -d '{"name":"北方港","chart_datum_depth":10.0}'
```

`GET /ports` 列表、`GET /ports/{id}` 详情、`DELETE /ports/{id}` 删除。

### 2. 录入 / 更正潮高预报点（整组替换）

```bash
curl -X PUT http://localhost:8000/ports/1/forecasts \
  -H 'Content-Type: application/json' \
  -d '{"points":[
    {"time":"2026-09-24T00:00:00Z","height":0.0},
    {"time":"2026-09-24T04:00:00Z","height":4.0},
    {"time":"2026-09-24T06:00:00Z","height":2.0},
    {"time":"2026-09-24T08:00:00Z","height":0.0}
  ]}'
```

- 至少 2 个点，时刻不可重复，顺序任意（内部排序）。
- **预报更正就是再次 PUT 全量点**，之后所有查询立即按新数据计算。
- `GET /ports/{id}/forecasts` 查看当前最新预报点。

### 3. 查询通航窗口

```bash
curl -X POST http://localhost:8000/ports/1/navigation-windows \
  -H 'Content-Type: application/json' \
  -d '{
    "draft": 11.5,
    "under_keel_clearance": 0.5,
    "navigation_duration_minutes": 240
  }'
```

响应示例：

```json
{
  "port_id": 1,
  "port_name": "北方港",
  "required_depth": 12.0,
  "navigation_duration_minutes": 240.0,
  "coverage_start": "2026-09-24T00:00:00Z",
  "coverage_end": "2026-09-24T08:00:00Z",
  "departure_windows": [
    {
      "window_start": "2026-09-24T02:00:00Z",
      "window_end": "2026-09-24T06:00:00Z",
      "depart_from": "2026-09-24T02:00:00Z",
      "depart_to": "2026-09-24T06:00:00Z",
      "window_duration_minutes": 240.0
    }
  ],
  "earliest_departure": "2026-09-24T02:00:00Z",
  "count": 1
}
```

上例中潮高在 02:00 线性升至临界 2 m（水深恰好 12 m），06:00 恰好回到 2 m，达标窗口 `[02:00, 06:00]` 恰好 4 小时被保留；可出发时段为 `[02:00, 06:00]`。

**参数约束**：`draft > 0`、`under_keel_clearance ≥ 0`、`navigation_duration_minutes > 0`。

**状态码**：`200` 成功；`400` 预报点不足 2 个 / 算法参数非法；`404` 港口不存在；`409` 港口重名；`422` 请求体校验失败。

## 本地开发（不使用 Docker）

```bash
pip install -r requirements.txt
export DB_PATH=./data/tides.db SEED_DEMO=1
sh entrypoint.sh        # 建库 + 种子 + 启动
# 或开发热重载:
python3 -m uvicorn app.main:app --reload --port 8000
```

### 运行测试

```bash
pip install -r requirements.txt httpx
python3 -m unittest discover -s tests -v
```

- `tests/test_algorithm.py`：插值、端点恰好达标、窗口合并、不足时长舍弃、可出发时段等 10 个用例（纯算法，无需 FastAPI）。
- `tests/test_api.py`：建港 → 录预报 → 查询 → 预报更正后重算的端到端冒烟测试。

## 项目结构

```
.
├── app/
│   ├── algorithm.py   # 线性插值 + 连续窗口/可出发时段核心算法 (无副作用)
│   ├── db.py          # SQLite 访问层 (WAL, 事务化整组替换)
│   ├── main.py        # FastAPI 路由与装配
│   ├── schemas.py     # 请求/响应模型与校验
│   └── seed.py        # 可选演示数据 (幂等)
├── tests/             # 单元测试 + API 冒烟测试
├── entrypoint.sh      # 容器入口: 初始化 DB -> 种子 -> 启动
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 设计说明

- 算法层（`app/algorithm.py`）是纯函数，不碰数据库，便于单独测试与复核；API 层只负责读取最新预报点并调用它。
- 单进程 uvicorn + SQLite（WAL）：写操作（预报替换）经进程内锁串行化，读操作可并发，满足本场景吞吐；若未来多进程部署，将写操作收敛到单写者或改用 WAL + 重试即可。
- 平潮线段（相邻点潮高相等）单独处理：全程达标则整段纳入，全程不达标则丢弃，临界交点不会产生除零问题。
