#!/usr/bin/env python3
"""
验证 embedding 计费：通过 Router **staging** 发真实 /v1/embeddings 请求，
累计响应里的 usage.prompt_tokens，按配置的单价算出"预期扣费"，
拿去跟 staging 账户 UI 上实际扣掉的余额对比。

这是 staging 环境（router-api-staging.0g.ai），不是 prod——如果要测 prod
账户的计费，用同目录下的 test-embedding-usage-billing-prod.py。

⚠️ ROUTER_API_KEY 要用 staging 账户的 key，不能跟 prod 那把混用——
staging 和 prod（router-api.0g.ai）是两个独立部署（各自独立的 GCP 项目 +
MySQL 数据库，见 0g-router CLAUDE.md 的部署架构一节），账户体系不共享。
prod 的 key 在 staging 这边查不到对应记录，会 401；反过来也一样。

为什么要凑到 >0.1 0G：账户余额 UI 只显示 2 位小数，扣费太小会被舍入吃掉，
看不出账目对不对（具体阈值按你 staging 账户当前余额自己调整
TARGET_TOTAL_TOKENS）。

**这一步脚本做不到，需要你自己手动做**：
  1. 运行脚本前，先在 staging 账户页面记下当前余额。
  2. 运行脚本，等它跑完打印出"预期扣费 (0G)"。
  3. 刷新账户页面，记下新余额，算 (运行前 - 运行后)。
  4. 跟脚本打印的预期值比较——broker 的价格 feed 每小时才更新一次、且有
     ±5% 波动带,跟脚本抓取的 CoinGecko 现价不会完全一致,小幅偏差正常;
     差距很大（比如差好几倍、或者方向反了）才说明计费有问题。
     （Router 的 /v1/account/balance 只认 JWT/mgmt key，推理用的 sk- key
     一律 403 insufficient_scope，所以脚本自己读不到余额，见 0g-router
     CLAUDE.md 的 API 接口表。）

用法：
    export ROUTER_API_KEY=sk-...   # staging 账户的 key，不是 prod 那把
    python3 test-embedding-usage-billing-staging.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROUTER_URL = "https://router-api-staging.0g.ai/v1/embeddings"
MODEL = "qwen3.7-text-embedding"

# deploy/phala/2-mainnet/35-qwen3.7-text-embedding/user_config:
# inputPriceUSDPerMillionTokens: "0.0777"
# 注意：这是本地 deploy 仓库 clone 里追踪到的值，跟 prod 实测的 0.0735 不同
# （prod 那边应该是后来又更新过价格，本地 clone 没有 push 权限拿不到最新
# 提交）。staging 走的是同一个 provider 部署，实际生效单价理论上应该跟
# prod 一致——如果要跟这边的"预期扣费"精确对账，运行前最好先用
# GET https://router-api-staging.0g.ai/v1/models 查一下 staging 这边
# pricing_usd.prompt 的实时值，跟下面这个数不一致就以实时查到的为准。
PRICE_USD_PER_M_TOKENS = 0.0777

# CoinGecko (id: zero-gravity) 现价快照，写这个脚本时查的——运行前最好重新
# 查一次 https://api.coingecko.com/api/v3/simple/price?ids=zero-gravity&vs_currencies=usd
# 更新这个数，broker 自己的价格 feed 每小时才更新、且有 ±5% 波动带，不会跟
# 现价完全一致，但差太远说明这个参考价过期了。
ZG_USD_REFERENCE = 0.198774

# 650,000 tokens：即使 0G 现价跟 broker 价格 feed 之间有 ±5% 的正常偏差，
# 换算出的 0G 扣费也稳稳超过 0.1 0G，不会卡在舍入误差附近看不清楚。
TARGET_TOTAL_TOKENS = 650_000

# 留足余量，远低于这个模型 128,000 tokens 的 context 上限（user_config 里
# modelInfo.contextLength），避免单次请求撞上游限制。
MAX_TOKENS_PER_REQUEST = 100_000

# 固定、确定性的英文文本，纯 ASCII，重复拼接来堆量。
UNIT = "The quick brown fox jumps over the lazy dog. "

API_KEY = os.environ.get("ROUTER_API_KEY")
if not API_KEY:
    sys.exit("先 export ROUTER_API_KEY=sk-...")


def call_embedding(text):
    body = json.dumps({"model": MODEL, "input": text}).encode()
    req = urllib.request.Request(
        ROUTER_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        raise


def main():
    print(f"目标总 token 数: {TARGET_TOTAL_TOKENS:,}")
    print("=" * 60)

    # 校准：先发一小段，量出这个 tokenizer 真实的 token/word 比例——不用
    # router 自己那套 CJK 估算公式，那是路由层预判用的，跟 Aliyun 真实
    # 计费的 tokenizer 无关，实际扣费以响应里的 usage.prompt_tokens 为准。
    calib_repeats = 500
    calib_resp = call_embedding(UNIT * calib_repeats)
    calib_tokens = calib_resp["usage"]["prompt_tokens"]
    tokens_per_unit = calib_tokens / calib_repeats
    print(
        f"校准请求: {calib_repeats} 次重复 -> {calib_tokens} tokens "
        f"(每次重复 ≈ {tokens_per_unit:.3f} tokens)"
    )

    total_tokens = calib_tokens  # 校准请求本身也真实计费，要计入累计
    repeats_per_request = max(1, int(MAX_TOKENS_PER_REQUEST / tokens_per_unit))

    request_no = 1
    while total_tokens < TARGET_TOTAL_TOKENS:
        resp = call_embedding(UNIT * repeats_per_request)
        tokens = resp["usage"]["prompt_tokens"]
        total_tokens += tokens
        print(f"请求 #{request_no}: {tokens:,} tokens (累计 {total_tokens:,})")
        request_no += 1
        time.sleep(1)  # 留点余量，别顶 perUserRPM

    print("=" * 60)
    cost_usd = total_tokens * PRICE_USD_PER_M_TOKENS / 1_000_000
    cost_0g_ref = cost_usd / ZG_USD_REFERENCE
    print(f"实际总 token 数: {total_tokens:,}")
    print(
        f"预期扣费 (USD)  : {total_tokens:,} / 1,000,000 * {PRICE_USD_PER_M_TOKENS} "
        f"= ${cost_usd:.6f}"
    )
    print(
        f"预期扣费 (0G，按参考价 ${ZG_USD_REFERENCE}/0G): "
        f"${cost_usd:.6f} / {ZG_USD_REFERENCE} ≈ {cost_0g_ref:.4f} 0G"
    )
    print()
    print("现在去 staging 账户页面刷新余额，用「运行前余额 - 运行后余额」")
    print(f"跟上面的 {cost_0g_ref:.4f} 0G 做对比。")


if __name__ == "__main__":
    main()
