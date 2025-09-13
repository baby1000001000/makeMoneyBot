# 🚀 快速使用指南

## 第一次使用？ 5分钟快速上手！

### 1️⃣ 环境准备 (1分钟)
```bash
git clone <your-repo-url>
cd makeMoneyBot
pip install -r requirements.txt
```

### 2️⃣ 配置API密钥 (2分钟)
```bash
# 复制模板
cp secrets.json.template secrets.json

# 编辑配置（填入你的真实API密钥）
nano secrets.json
```

### 3️⃣ 测试连接 (1分钟)
```bash
python arbitrage_bot.py
# 选择: 1. 🔍 状态检查
```

### 4️⃣ 开始套利 (1分钟)
```bash
# 选择: 3. ⚡ 执行套利
# 选择: d. MEXC->Gate套利（验证流程）
# 输入币种: XLM
# 输入金额: 5 (建议首次小额测试)
```

## ⚡ 超级快速版本

```bash
# 一键执行 (请先配置好secrets.json)
git clone <repo> && cd makeMoneyBot && pip install -r requirements.txt && python arbitrage_bot.py
```

## 🔥 推荐设置

```json
// secrets.json
{
  "mexc": {
    "api_key": "你的MEXC密钥",
    "secret_key": "你的MEXC秘钥"
  },
  "gate": {
    "api_key": "你的Gate密钥", 
    "secret_key": "你的Gate秘钥"
  }
}
```

## 🎯 最佳实践

1. **首次使用**: 5-10 USDT 测试
2. **推荐币种**: XLM, DOGE 
3. **执行模式**: 选择 "d. MEXC->Gate套利"
4. **监控**: 关注执行日志和收益

## ❗ 重要提醒

- ✅ 确保两个交易所都有足够余额
- ✅ API权限必须包含：交易+钱包+提现
- ✅ 首次建议小额测试
- ✅ 保持网络稳定

需要帮助？查看完整的 [README.md](README.md) 📖