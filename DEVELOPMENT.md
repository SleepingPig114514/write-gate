# write-gate Development

开发文档。给改这个仓库的人看。**不会被复制到 Hermes 运行时副本**（只 cp `__init__.py / plugin.yaml / README.md / CHANGELOG.md`）。

## 仓库身份

- GitHub: https://github.com/SleepingPig114514/write-gate
- 当前版本：v1.0.0（HEAD: `9bbc85b`）
- 运行时副本：`C:\Users\12\AppData\Local\hermes\plugins\write-gate\`（Hermes 按需 import）
- 用户文档：[README.md](README.md)

## 三处同步关系

| 位置 | 角色 |
|---|---|
| GitHub main 分支 | 公开版本，对外 |
| `D:/AI agent workspace/main/write-gate/`（这个仓库）| 本地开发源，跟 GitHub 同步 |
| `C:\Users\12\AppData\Local\hermes\plugins\write-gate\` | Hermes 跑的构建副本 |

**两份本地（workspace 仓库 + Hermes 副本）应当保持一致，但不自动同步。**

### 同步方向

| 改在哪儿 | 怎么同步到对方 |
|---|---|
| 本仓库 → 推 GitHub | `git push origin main` |
| 本仓库 → 装到 Hermes | `cp __init__.py plugin.yaml README.md CHANGELOG.md "C:/Users/12/AppData/Local/hermes/plugins/write-gate/"`（**不** cp DEVELOPMENT.md） |
| Hermes 那份改了 → 回本仓库 | 手动复制文件 + `git diff` 检查 + commit |
| GitHub 拉新 → 本仓库 | `git pull origin main` |

### 同步注意

- 改 Hermes 那份不会自动 commit 到本仓库，**会丢历史**
- 改完本仓库后没 `cp` 到 Hermes 那份，新代码不会生效（直到下次 pre_tool_call 触发重读）
- 改 `plugin.yaml` 的 version 时，记得同步 `CHANGELOG.md` 加新条目
- `README.md` 是**用户向**的文档，不是开发向——开发内容请放本文件

## 仓库结构

| 文件 | 谁看 | 修改风险 |
|---|---|---|
| `__init__.py` | 开发者 | 高 — 直接改变闸门行为 |
| `plugin.yaml` | 开发者 | 中 — 改 version 要同步 CHANGELOG |
| `README.md` | **终端用户** | 低 — 但改坏会影响用户理解 |
| `CHANGELOG.md` | 终端用户 + 开发者 | 低 — 文档 |
| `LICENSE` | — | 极低 — 别动 |
| `DEVELOPMENT.md` | 开发者 | 低 — 别 cp 到 Hermes（**仅仓库存在，Hermes 副本不装**） |

## 发布流程（变更 → GitHub → Hermes 副本）

1. 改 `__init__.py` 等代码，验证（参考 main/AGENTS.md「通用经验教训」第三条「在用户的真实运行环境验证」）
2. 改 `plugin.yaml` 的 `version`（如 `1.0.0` → `1.0.1`）
3. 改 `CHANGELOG.md`，加新条目（描述本版本改了什么）
4. `git add . && git commit -m "Release vX.Y.Z: ..."`
5. `git push origin main`
6. `cp __init__.py plugin.yaml README.md CHANGELOG.md "C:/Users/12/AppData/Local/hermes/plugins/write-gate/"`
7. （可选）重启 gateway 让插件代码立即重读：`hermes gateway restart`

## License

MIT