# 🤖 Crypto Arbitrage Bot - 加密货币套利机器人

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-success)]()

自动化加密货币套利系统，支持 MEXC 和 Gate.io 交易所之间的实时价差监控和自动套利交易。

## 🚀 功能特性

- ✅ **双平台支持**: 支持LBank和Gate.io两大交易所
- ✅ **实时监控**: 1秒级价差监控，及时发现套利机会
- ✅ **自动执行**: 全流程自动化套利交易
- ✅ **风险控制**: 多重安全机制，保护资金安全
- ✅ **详细日志**: 完整的交易记录和资金流水追溯
- ✅ **友好界面**: 直观的菜单系统，操作简单

## 📋 系统要求

- Python 3.9+
- 网络连接稳定
- LBank和Gate.io API密钥

## 🛠️ 安装步骤

### 1. 环境准备

```bash
# 创建虚拟环境
python3 -m venv makeMoneyBot

# 激活虚拟环境
source makeMoneyBot/bin/activate  # Linux/Mac
# 或
makeMoneyBot\\Scripts\\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置API密钥

**方式一：直接在config.yaml中配置（推荐）**

编辑 `config.yaml` 文件，找到 `api_keys` 和 `addresses` 部分，填入您的真实信息：

```yaml
# API密钥配置
api_keys:
  lbank:
    api_key: "您的LBank API密钥"
    secret_key: "您的LBank私钥"
    signature_method: "RSA"
  
  gate:
    api_key: "您的Gate API密钥"
    secret_key: "您的Gate私钥"

# 充提地址配置
addresses:
  gate:
    USDT:
      BSC: "您的Gate USDT BSC地址"
      TRX: "您的Gate USDT TRX地址"
    TBC:
      TBC: "您的Gate TBC地址"
  lbank:
    USDT:
      BSC: "您的LBank USDT BSC地址"  
      TRX: "您的LBank USDT TRX地址"
    TBC:
      TBC: "您的LBank TBC地址"
```

**方式二：独立配置文件（更安全）**

如需更高安全性，可创建独立的 `参数配置.md` 文件：

```yaml
lbank:
  api_key: "your_lbank_api_key"
  secret_key: "your_lbank_private_key"
  signature_method: "RSA"

gate:
  api_key: "your_gate_api_key"
  secret_key: "your_gate_secret_key"

addresses:
  # ... 地址配置
```

⚠️ **安全提醒**: 如使用方式一，请确保不要将包含API密钥的config.yaml提交到Git仓库

## 🏦 自动获取充值地址

**好消息！** 系统现在可以自动通过API获取充值地址，无需手动配置：

✅ **智能获取**: 优先通过交易所API自动获取最新地址  
✅ **多链支持**: 自动选择最优网络（BSC/TRX）  
✅ **地址缓存**: 避免重复API调用，提高效率  
✅ **备选方案**: API失败时自动使用配置文件中的地址  

您可以通过菜单系统的"配置管理"查看自动获取的地址信息。

### 3. 运行程序

```bash
python main.py
```

## 📖 使用说明

### 主菜单功能

1. **🔍 状态检查**: 验证API连接和权限
2. **📊 套利查询**: 查看当前价差和套利机会
3. **📝 配置管理**: 修改套利参数设置
4. **⚡ 执行套利**: 手动或自动执行套利交易
5. **📝 交易日志**: 查看历史交易记录
6. **🌐 获取IP**: 获取当前IP用于白名单配置
7. **🌍 代理配置**: 配置网络代理
8. **🚪 退出系统**: 安全退出程序

### 套利流程

1. **价差监控**: 实时监控TBC在两个交易所的价格差异
2. **机会识别**: 当价差超过设定阈值时触发套利
3. **买入执行**: 在价格较低的交易所买入TBC
4. **转账过程**: 将买入的TBC转到价格较高的交易所
5. **卖出完成**: 在目标交易所卖出TBC获得USDT
6. **资金回流**: 将获得的USDT转回原始交易所
7. **利润结算**: 完成一轮套利，记录盈亏

## ⚠️ 风险提示

- 加密货币交易存在极大风险，可能导致资金损失
- 套利交易受网络延迟、滑点等因素影响，收益不保证
- 请仅使用您能承受损失的资金进行交易
- 建议先在测试模式下熟悉系统操作

## 🔧 配置说明

### config.yaml 主要参数

```yaml
app:
  min_spread_bps: 50          # 最小价差(基点)，50=0.5%
  min_profit_usdt: 0.1        # 最小利润阈值(USDT)
  initial_budget_usdt: 100    # 初始预算(USDT)
  
arbitrage:
  monitor_interval_sec: 1     # 监控间隔(秒)
  min_arbitrage_amount_usdt: 50   # 最小套利金额
  max_arbitrage_amount_usdt: 5000 # 最大套利金额
  
risk:
  pnl_floor_usdt: -50         # 最大亏损限制
  max_single_trade_usdt: 1000 # 单笔最大交易额
```

## 📊 日志说明

系统生成三类日志文件：

1. **arbitrage.log**: 系统运行日志
2. **trade_history.log**: 交易操作记录
3. **fund_flow.log**: 资金流水记录

日志格式示例：
```
[2025-01-01 12:00:00:123][983819218]lbank-> 购买 100 USDT的TBC
[2025-01-01 12:00:01:456][983819218]lbank-> 向gate转出 13.25 TBC
[2025-01-01 12:00:05:789][983819218]gate-> 收到充值 13.25 TBC
```

## 🤝 支持与反馈

如遇到问题或需要技术支持，请：

1. 检查配置文件格式是否正确
2. 确认API密钥权限是否充足
3. 查看系统日志了解错误详情
4. 检查网络连接和交易所API状态

## 📄 免责声明

本软件仅供学习和研究使用，使用者需自行承担所有交易风险。开发者不对因使用本软件而产生的任何直接或间接损失负责。

---

**⚡ 开始您的套利之旅，但请谨慎交易！**