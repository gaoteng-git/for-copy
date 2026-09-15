# 0G Compute 网络代币流动全流程

## 一、用户 → router

1. 用户把 0G 存进 **`RouterPayment` 合约**（不是转给 router 钱包）。链上 `Deposit` 事件同步到 router 数据库的 `deposit_balance`。
2. 每次推理请求，只在 router 的 MySQL 里扣减 `deposit_balance`、累加 `total_consumed`——**链下记账，不是真实转账**。
3. `SettleWorker` 定期（部署环境 60 秒）把攒够 `min_amount` 的用户打包，一次 `sendBatchSettle` 上链：`RouterPayment` 合约按 `userBalances` 里记录的已消费额，把对应的 0G 转到 router 自己的结算钱包。

**为什么要用合约，而不是直接信任 router**：router 的结算私钥能对 `RouterPayment` 做的操作，只有合约代码允许的那几个函数（核心是 `batchSettle`），且转出金额受合约自己维护的 `userBalances` 约束——**即使私钥泄露，攻击者能拿走的上限也只是"用户已产生的消费额"，碰不到用户还没花的钱**。用户信任的是公开可审计的合约代码，不是 router 这家运营方的品行。

## 二、router → provider（broker）

router 在这套体系里，本身也是"0G Compute 账户合约"上的一个普通用户：

- 有自己的**主账户**，并且**给每个它要调用的 provider 各开一个独立的 sub-account**（一对一，不是共用一个）。
- provider（broker）结算时，从**这个 provider 专属的 sub-account** 里扣款，而不是从 router 的钱包或主账户里直接拿。
- 结算需要 **TEE 签名证明**（`SettleFeesWithTEE`，接收一份 TEE 签过名的结算数据），provider 不能凭空报数字扣款，必须证明这笔钱对应一次真实、经 TEE 验证过的推理——比 router 对普通用户的结算门槛更高。
- 结算方式和第一段完全对称：broker 自己也有一套批量结算机制（`SettlementProcessor`，`checkSettleInterval` 默认 5 分钟 + `forceSettleInterval` 默认 10 分钟两个 ticker），攒够一批已完成请求后一次性上链结算，不是每次请求都单独上链。

**普通用户直连 broker**（不经 router）：逻辑完全一样，只是 sub-account 的持有者换成这个终端用户自己的地址。

**⚠️ 悬而未决的一环**：router 的 sub-account 余额只会随消费减少，谁来给它充值？把 router 两个仓库（`nodejs-service`、Go 后端全部 worker）都搜了一遍，**没有找到任何自动充值 provider sub-account 的代码**：
- `nodejs-service/src/services/sdk.ts` 只暴露 `getRequestHeaders`/`acknowledgeProviderSigner`/`createApiKey`/`revokeApiKey`，没有 deposit 类函数。
- `revenue_transfer_worker.go` 反而是把 router 钱包里**超出预留额度的钱转给基金会**，方向是"往外流"，不是"往 sub-account 里补"。

结论：router 钱包的钱从 `SettleWorker` 流入、被 `RevenueTransferWorker` 定期抽走给基金会，而 sub-account 的充值大概率是这两个仓库之外的**人工/运维操作**（财务侧拿着 SDK 或钱包工具手动打钱），代码层面确认不了具体频率和触发方式——这个问题需要直接问负责链上运维的同事。

## 三、provider 自己的成本与收入

- **自建 GPU 跑模型**：消耗自己的机时，赚的是纯代币差价（sub-account 结算进账 - 电费/硬件成本，后者不在链上体现）。
- **调用第三方 API（阿里/字节等）**：provider 自己的 API key 账户被第三方按美元/人民币实时扣款，同时从 sub-account 收到代币结算——两套结算体系完全独立，provider 赚"代币收入 - 第三方法币成本"的差价。

## 四、两段结算的对称性总览

| | 用户 ↔ router | router(或直连用户) ↔ provider |
|---|---|---|
| 托管合约 | `RouterPayment` | 0G Compute 账户/ledger 合约 |
| 记账方式 | 先落 router MySQL，再批量上链 | 先落 broker 自己的请求记录，再批量上链 |
| 批量 worker | `SettleWorker` | `SettlementProcessor` |
| 间隔 | 部署环境 60 秒 | 默认 5 分钟 / 强制 10 分钟 |
| 扣款凭证 | 合约自记的 `userBalances` | TEE 签名的结算数据 |
| 资金去向 | router 结算钱包 | provider 专属 sub-account 扣减 |

一句话：router 对它的用户扮演"provider"的角色（收币、记账、批量结算），对真正的 provider 又扮演"用户"的角色（sub-account、批量结算、TEE 验证）——同一套"落库 → 批量上链"的模式在两段各跑一遍，只是身份互换、且第二段多了 TEE 证明这道门槛。sub-account 的**充值**是目前唯一没有在代码里找到自动化实现的一环。

## 五、通俗理解：合约 / 链 / 钱包 / 权限

### 合约

- **公开**：代码部署在链上，任何人都能读、能审计。
- **可信** ≈ "可预测"，不是人际关系意义上的可信。合约没有意图，只会精确执行写死的逻辑——信的是"我审过代码，知道它会做什么"，不是信运营方的承诺。
- **不会被篡改**：**不是绝对的**，取决于合约怎么写。普通合约部署后字节码不能改；但可升级合约（proxy pattern）逻辑能被替换，这时信任点转移到"谁握着升级权限、是不是多签、有没有 timelock"上。

### 链

不是"存代币和数据的地方"，更准确说：链上**没有代币这个实体**，代币就是账本里记的一个数字，归属于某个地址。链是很多个互不隶属的节点共同维护、公开可查、几乎无法被单方篡改历史记录的**状态记录系统**。"公开不可篡改"不是靠承诺，是靠"记账的人足够多、足够分散"这个结构本身。

### 存放代币的两种地方

- **EOA（钱包）**：由私钥控制，没有代码。谁有私钥，谁就能随意转走里面的钱——**认钥匙不认规矩**。
- **合约账户**：有代码、有自己的 storage，也能持有余额，但**没有私钥**。余额只能按照合约代码写死的逻辑转出，不存在"谁掌握密钥就能动它"——**认规矩不认人**。

### 类比传统金融

| 概念 | 类比 |
|---|---|
| EOA / 私钥签名 | 你自己的保险箱，谁拿钥匙谁能开锁拿钱，没有任何审查环节 |
| 合约账户 | 一份自动执行的信托/托管协议（escrow）：钱放进去后没人能像开保险箱一样直接拿走，能不能动、动多少、什么条件下动，全写死在条款里，条件满足自动执行 |
| 不可升级合约 | 已签字、不能再改的合同 |
| 可升级合约 | 公司章程：理事会（多签）以后还能表决修改条款，信任对象变成"这个理事会靠不靠谱、有没有 timelock" |
| 链 | 很多个独立公证人各自记一份账、互相核对，想改历史记录要说服绝大多数人一起改，实践上做不到 |
| sub-account | 证券/信托行业的 "omnibus account"：银行只看到一个总账户，公司内部一本 mapping 精确记着"张三多少、李四多少"，代币物理上从来没有分开存放 |

一句话收尾：钱包的规则是"认钥匙"，合约的规则是"认合同条款"——把钱存进合约，本质是把这笔钱的支配权从"谁有私钥"，转移给了"谁写的代码逻辑"。

## 六、这些合约是 0G 自己写的，还是第三方的

核实结论：**核心业务合约都是 0G 自己团队写的，不是外部第三方合约**，但底层用了业界标准的第三方基础库。

- **router 侧 `RouterPayment` 合约**：源码就在 `0g-router` 仓库里（`contracts/contracts/RouterPayment.sol`），router 团队自己写、自己部署维护（`deployments/zgMainnet/`、`zgTestnetV4/` 能看到实际部署记录）。
- **broker 侧 `InferenceServing`/`FineTuningServing` 合约**：不在 `0g-serving-broker` 仓库里，而是在独立的 git submodule `github.com/0glabs/0g-serving-contract`（`.gitmodules` 里能看到）。`0glabs` 是 0G 官方 GitHub 组织（和 `0glabs/0g-serving-broker` 自己同一个组织），所以也是 0G 自己维护的，只是拆成了独立仓库，broker 用 abigen 从它的 ABI 生成 Go 绑定。
- **真正的第三方部分：OpenZeppelin**。`RouterPayment.sol` 里 `import "@openzeppelin/contracts/access/Ownable.sol"`——权限控制、可升级代理这类"基础设施级"代码复用了以太坊生态最主流、审计最多的开源库，没有自己重写。这属于行业公认的标准件，相当于写后端服务用 `gin`/`express` 这种基础框架，不是把业务逻辑外包出去。

一句话：业务逻辑（谁的钱、怎么扣、sub-account 怎么分）全是 0G 自己写的；权限控制、代理升级这类"轮子"用的是 OpenZeppelin。

## 七、sub-account 不能自动充值，意味着什么

合约里的 `Account` 按 `(user, provider)` 这一对地址查，每一对独立记账、独立余额，充值必须显式指定 provider（`depositFund`），**没有"余额不足自动从别处补"这种机制**。

推论：一个绕过 router、直连 provider 的用户，用几个 provider 就要开几个账户、各自盯着充值——账户数随 provider 数线性增长，资金还会分散锁死在多个账户里用不到别处。

Router 的定位文档明说了这就是它要解决的问题之一：**"费用代收：用户向 Router 付费，Router 管理与各 Provider 的结算"**——用户只维护一个关系（和 router），router 内部替他把这笔钱拆给 N 个 provider。

但这不是"问题消失了"，只是"从每个终端用户各自面对，收敛成 router 一个运营方集中面对"——router 自己管理这堆 sub-account 目前同样没找到自动化充值代码，很可能也是人工运维在盯。本质是规模化分工：让一个专业团队处理，比让所有终端用户各自学会盯合约余额划算。
