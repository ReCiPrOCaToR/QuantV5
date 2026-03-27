# QuantV5 Quick Start

## 环境准备

```powershell
cd D:\My_Project\QuantV5
pip install -r requirements.txt
```

确保 `.env` 文件已配置 Alpaca API Key：
```
APCA_API_KEY_ID=你的key
APCA_API_SECRET_KEY=你的secret
```

## 常用命令

### 下载/刷新历史数据
```powershell
python download_missing.py
```

### 回测
```powershell
python -c "from strategy_sector import SectorRotation; import data_cache; etfs=['XLK','XLE','XLF','XLV','XLU','XLP','XLI','XLRE','XBI']; d={s:data_cache.get(s,730) for s in etfs}; spy=data_cache.get('SPY',730); r=SectorRotation().run(d,spy); print(r)"
```

### 实盘扫描（只看信号，不下单）
```powershell
python live_trader_v5.py scan
```

### 实盘交易（执行买卖）
```powershell
python live_trader_v5.py
```

### 启动 Web 仪表盘
```powershell
python server.py
# 浏览器打开 http://localhost:5000
```

### 仪表盘操作

启动后在浏览器中操作：

| 按钮 | 功能 |
|------|------|
| **Run Backtest** | 运行回测（选择策略版本和时间范围） |
| **Walk-Forward** | 运行 Walk-Forward 验证 |
| **Scan** | 扫描信号，只看排名不下单 |
| **Execute Trades** | 执行交易（会弹出确认框） |
| **Strategy Info** | 查看当前策略信息和持仓 |

### Walk-Forward 验证
```powershell
python walk_forward.py
```

## 项目结构

```
QuantV5/
├── strategy_sector.py  # V5 策略 + 回测引擎
├── live_trader_v5.py   # V5 实盘交易
├── live_state_v5.json  # 部署状态记录
├── server.py           # Flask 仪表盘
├── dashboard.html      # 前端 UI
├── walk_forward.py     # Walk-forward 验证
├── config.py           # 配置（API Key 等）
├── indicators.py       # 技术指标
├── signals.py          # 信号评分（v2 遗留）
├── data_cache.py       # 磁盘缓存
├── download_batch.py   # 批量下载数据
├── download_missing.py # 补充下载数据
├── requirements.txt    # Python 依赖
├── .env                # API 密钥（勿提交）
└── data/cache/         # 历史数据缓存
```

## 策略说明

**V5 Sector ETF Rotation**：
- 选股池：9 个行业 ETF（XLK/XLE/XLF/XLV/XLU/XLP/XLI/XLRE/XBI）
- 信号：30 日相对强度（ETF 回报 - SPY 回报）
- 持仓：Top 2 相对强度为正的行业 ETF
- 调仓：每 15 个交易日
- 趋势过滤：SPY < SMA200 → 50% 现金
- 止损：10% 吊灯止盈

## GitHub

仓库地址：https://github.com/ReCiPrOCaToR/QuantV5.git

```powershell
git pull   # 拉取最新代码
git push   # 推送本地修改
```
