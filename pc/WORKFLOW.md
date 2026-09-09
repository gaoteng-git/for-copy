# 部署操作手册 —— phala 主网/测试网 provider

日常怎么用这个仓库。两种角色:

- **开发者(Developer)** —— 负责一个或多个 provider 的**配置**。可以 clone 整个
  仓库、编辑 provider 配置、push。**不能**查看或设置密钥、不能改控制文件、不能部署。
- **管理员(Admin)** —— 持有全部密钥,掌管部署控制文件,执行部署和链上 `ack`,
  负责新增 provider / 密钥。

## 先读:密钥模型

- **仓库里没有任何密钥。** `user_config` / `env` 里每一处私钥、API token 都是
  `${占位符}`。任何人 clone 仓库都拿不到真实密钥。
- **真实密钥只在**两处:bastion 密钥库
  `cvm-team:/dstack/persistent/.secrets/<provider>/`,以及管理员本机的副本。
  部署时由 `redeploy.sh` 的 *render* 步骤注入。
- 开发者的 SSH key 被限制为只能 git(无 shell、碰不到密钥库);管理员在 bastion
  上有 shell、本机有密钥副本。

**支持的占位符**(部署时注入到 `user_config`):
`${PRIVATE_KEY}`、`${AUTHORIZATION}`(多个时 `${AUTHORIZATION_2}`…)、`${COINGECKO_API_KEY}`。
`env` 里的基建密钥(`${CLOUDFLARE_API_TOKEN}`、`${PROMETHEUS_CONFIG}`、
`${ALIYUN_ARMS_*}`)是**带外**的 —— 它们留在 CVM 上,`redeploy.sh` 不部署 env。

---

## 准备:配置到 bastion 的连接(`cvm-team` 是什么)

`cvm-team` 是本文里到处出现的一个 **SSH 主机别名**,指向我们的 **bastion**——一台
Phala dstack **TEE 机密虚拟机**,同时充当:① 私有 git 服务器(裸库 `deploy.git`,
你 clone/push 的就是它);② 密钥库(`.secrets/`)。所有人都通过这个别名、经一条
openssl TLS 隧道连到它的 `:443`。

**用之前,在你自己的 `~/.ssh/config` 里加这段**(否则 `cvm-team:...` 无法解析、
clone 会报 "Could not resolve hostname"):
```
Host cvm-team
  HostName 93f6678be37e34c2a72d181af8ebf4f6ec39f4d8-22.dstack-pha-in2.phala.network
  Port 443
  User root
  ProxyCommand openssl s_client -quiet -connect %h:%p
```
- 连接用你的 **SSH key**:开发者的 key 被限制为只能 git(强制命令,无 shell);
  管理员的 key 能进 shell。两种角色用**同一段配置**,区别只在你被授权的是哪把 key。
  你需要先把自己的 **SSH 公钥**交给管理员加进 bastion 授权列表。
- 需要本机装有 `openssl`(ProxyCommand 用它做 TLS 隧道)。
- ⚠️ 这台 CVM 若被重建,`HostName` 那串会变;连不上时找管理员要最新的 HostName。

---

## 一次性设置

### 开发者
```sh
git clone cvm-team:/git/deploy.git deploy
cd deploy
```
就这样。你的 key 挂了强制命令(git-only),git 请求会被自动路由到 bastion 容器里的
git,**不要**加 `--upload-pack`,也**不要**设 uploadpack/receivepack 覆盖 —— 那会让强制
命令收到一个全路径 verb 反而被拒。你不需要密钥,也不需要 CVM 访问权。

### 管理员
```sh
# 1. clone(管理员是 shell key、无强制命令,需指定 upload-pack 全路径并配好覆盖,
#    否则非交互 shell 的 PATH 里找不到 git-upload-pack)
git clone --upload-pack=/dstack/persistent/bin/git-upload-pack \
    cvm-team:/git/deploy.git deploy
cd deploy
git config remote.origin.uploadpack  /dstack/persistent/bin/git-upload-pack
git config remote.origin.receivepack /dstack/persistent/bin/git-receive-pack
# 2. 拉一份本机密钥副本(权威源是 bastion)
scp -r cvm-team:/dstack/persistent/.secrets ~/.0g-deploy-secrets
# 3. 保存 smoke tokens 文件(放在仓库之外)
cp <老checkout>/inferene-api-key/0-all-monitor/access-tokens-mainnet.json ~/.0g-deploy-secrets/
# 4. 本机 0g-compute-cli 用合约 owner key 登录好(ack 用)—— 和以前一样
```
可选的 shell 快捷函数(写进 `~/.zshrc`):
```sh
0g-deploy() { SECRETS_DIR=~/.0g-deploy-secrets \
  ./redeploy.sh --tokens ~/.0g-deploy-secrets/access-tokens-mainnet.json "$@"; }
```
下面所有 `redeploy.sh` 命令都在 `phala/2-mainnet/` 目录下执行。

---

## 管理员:授权 / 移除一个开发者(发放访问)

新开发者要能 clone/push,得先由管理员把他的 SSH 公钥加进 bastion 授权列表,并限制为
**git-only、无 shell**。用脚本做,**别手改 `authorized_keys`**——这是单 root TEE 盒子,
手改一旦漏挂强制命令 = 对方拿到 root、或把自己锁死。

```sh
# 开发者把公钥发你(~/.ssh/id_ed25519.pub 的内容,或整个文件)
./bastion/authorize-dev.sh "<公钥文件路径 或 'ssh-ed25519 AAAA... dev@x'>"
#   先预览不动手:加 --dry-run
#   仅在开通自助部署(mode A)后:加 --deploy 再多授一把"触发部署"的 key
```
脚本行为(安全幂等):备份 `authorized_keys` → **只追加**(不改已有行)→ 已存在则跳过 →
行数变少就拒绝。授权后,开发者照「准备」那节配好 `~/.ssh/config` 即可 clone/push。

**移除一个开发者**:登录 bastion 删掉他那一行(保留你自己的 shell key):
```sh
ssh cvm-team
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
grep -v 'dev@x' ~/.ssh/authorized_keys > /tmp/ak && mv /tmp/ak ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```
(`dev@x` 换成那把 key 的注释;确认删对了再退出。)

---

## 场景 1 —— 修改现有 provider 的配置并部署

**开发者**
```sh
git pull
# 编辑 phala/2-mainnet/<provider>/{user_config,docker-compose.yml,...}
#   - 定价、模型参数、限速、compose 结构:随便改
#   - 任何密钥值:保留 ${占位符},绝不要粘真实 key
git commit -am "tune <provider>: ..."
git push
# 通知管理员改了哪个 provider
```

**管理员**
```sh
git pull                          # 拿到开发者的改动
git diff HEAD@{1} -- <provider>   # 审查
SECRETS_DIR=~/.0g-deploy-secrets \
  ./redeploy.sh --tokens ~/.0g-deploy-secrets/access-tokens-mainnet.json --smoke <provider>
# render 注入密钥 -> scp+recreate 到 CVM -> ack -> smoke
```

---

## 场景 2 —— 新增一个 provider 并部署

**开发者**
```sh
git pull
mkdir phala/2-mainnet/<new>           # 例如 30-foo
# 加 docker-compose.yml、user_config、env 等
#   - 直接拷一个现有 provider 目录当模板
#   - 密钥位置写 ${PRIVATE_KEY} / ${AUTHORIZATION} / ${COINGECKO_API_KEY}
#   - 不要改 providers.tsv(那是控制文件,push 会被拒)
git add phala/2-mainnet/<new> && git commit -m "add <new> provider config"
git push
# 通知管理员:新 provider <new>、目标 CVM、以及上游 API key
# (API key 走带外渠道给,别放进仓库)
```

**管理员**
```sh
git pull
# 一条命令:生成钱包、建并发布 .secrets bundle、加 providers.tsv 行、加 ssh_config Host 块
./bastion/add-provider.sh --name <new> --host <cvm别名> \
    --auth "Bearer <上游key>" --cg "<coingecko-key>" \
    --ssh-hostname <新CVM地址>            # 新 CVM 才需要;复用已有别名则省略
#   端口/用户/代理默认 443 / root / openssl 隧道,可用 --ssh-port/--ssh-user/--ssh-proxy 改
# 它会打印后续手动步骤:
#   1) 给打印出的 provider 地址充 gas
#   2) 供给/复用 CVM <cvm别名>,并带外放好它的 env
SECRETS_DIR=~/.0g-deploy-secrets \
  ./redeploy.sh --tokens ~/.0g-deploy-secrets/access-tokens-mainnet.json --smoke <new>
# 把 providers.tsv + ssh_config 同步给所有人(否则别人解析不到这个 host 别名):
./bastion/owner-push-control.sh providers.tsv ssh_config
```
> 想复用一把已有的签名钱包而不是新生成:
> `add-provider.sh ... --key <64位hex>`。

---

## 场景 3 —— 轮换 / 修改密钥(仅管理员)

密钥从不进仓库,所以换 key 只动密钥库,不改仓库、不涉及开发者。
```sh
# 两处都改(bastion 是权威源):
ssh cvm-team 'vi /dstack/persistent/.secrets/<provider>/secrets.env'   # 或 env-oob.secrets
scp cvm-team:/dstack/persistent/.secrets/<provider>/secrets.env \
    ~/.0g-deploy-secrets/<provider>/secrets.env
# 重新部署生效
SECRETS_DIR=~/.0g-deploy-secrets ./redeploy.sh --smoke <provider>
```
若换的是**签名钱包**,重跑 `add-provider.sh --name <provider> --host <cvm>
--key <新hex> ...`(会重建 bundle + 地址),然后充值、重部署。

---

## 场景 4 —— 修改控制文件(仅管理员)

控制文件是 owner-only,服务端对所有人(包括管理员的普通 push)都拒:
`redeploy.sh`、`ssh_config`、`providers.tsv`、`bastion/*`、`known_hosts`、
`.gitattributes`。

本地改好,用辅助脚本推(它会短暂解除守卫再恢复):
```sh
# 编辑 phala/2-mainnet/providers.tsv(或 redeploy.sh、ssh_config …)
./bastion/owner-push-control.sh providers.tsv
```

---

## 场景 5 —— push 被拒 "REJECTED — owner-only deploy-control file"(开发者)

你的提交碰了控制文件(场景 4 那批)。只撤掉那个文件、保留你的 provider 配置改动:
```sh
git checkout origin/main -- phala/2-mainnet/providers.tsv   # 或被拒的那个文件
git commit --amend --no-edit
git push
```
如果你确实需要改控制文件(新增 provider 的 host 映射等),找管理员 —— 那是场景 2 / 场景 4。

---

## 速查

| 操作 | 开发者 | 管理员 |
|---|---|---|
| Clone / 读仓库 | ✅(无密钥) | ✅ |
| 改 provider 配置 + push | ✅ | ✅ |
| 改控制文件 | ❌ pre-receive 拒 | ✅ 走 `owner-push-control.sh` |
| 查看 / 设置密钥 | ❌ | ✅(bastion + 本机库) |
| 部署 + ack | ❌ | ✅ `redeploy.sh` |
| 新增 provider 配置 | ✅(占位符) | 用 `add-provider.sh` 收尾 |
| 授权 / 移除开发者 key | ❌ | ✅ `authorize-dev.sh` / 编辑 authorized_keys |

**部署命令**(管理员,在 `phala/2-mainnet/` 下):
```sh
SECRETS_DIR=~/.0g-deploy-secrets \
  ./redeploy.sh --tokens ~/.0g-deploy-secrets/access-tokens-mainnet.json --smoke <provider>
```
目标:一个或多个 provider 目录名,或 `all`。

> 说明:目前所有部署都由管理员执行(开发者 push、管理员部署)。将来可以开启
> "自助模式"(开发者在 bastion 上触发部署、自动 `ack`),无需改动以上任何内容;
> 需要时找管理员开通。
