# astrbot_plugin_hindsight_memory

这是一个 AstrBot 插件，用于接入 Hindsight Cloud，为私聊和群聊提供按会话隔离的长期记忆能力。

Hindsight 是一个面向 AI 应用的长期记忆服务，可以把对话中的信息沉淀到 Memory Bank，并在后续请求中按语义检索相关记忆。Hindsight Cloud 提供托管版 API 和后台管理界面，适合在不自建向量数据库、不维护记忆管理 WebUI 的情况下，为 Bot 增加可持续积累和召回的记忆能力。

插件不修改 AstrBot 核心，也不提供自定义 WebUI。配置仍然通过 AstrBot 根据 `_conf_schema.json` 生成的插件配置界面完成，记忆管理使用 Hindsight Cloud 自带后台。

## 功能特性

- 在每次 LLM 请求前，从 Hindsight Cloud 召回相关记忆。
- 通过 `extra_user_content_parts` 注入临时 `<hindsight_memory>` 内容，不写入 AstrBot 持久会话历史。
- 在 LLM 回复后，将本轮用户消息和助手回复写入 Hindsight Cloud。
- 私聊和群聊严格按 scope 隔离，避免跨会话、跨群召回。
- 发送到 Hindsight 的 sender ID、group ID、`unified_msg_origin` 都会先做 hash。
- 提供 `/hindsight` 命令，用于状态检查、手动召回和当前会话临时开关。

## 平台兼容性

已测试 AstrBot 平台：

- `aiocqhttp`
- `qq_official`
- `qq_official_webhook`

其他 AstrBot 平台理论兼容，未逐一测试。

## 安装与配置

1. 在 Hindsight Cloud 创建一个 Memory Bank。
2. 为该 Bank 创建 Bank-scoped API Key。
3. 将本仓库安装到 AstrBot 插件目录。
4. 在 AstrBot 插件配置中填写：
   - `api_key`：Hindsight Cloud API Key
   - `bank_id`：Hindsight Memory Bank ID
   - `api_base`：保持默认值 `https://api.hindsight.vectorize.io`
5. 保存配置后，重载插件或重启 AstrBot。

插件依赖只包含 `httpx`，AstrBot 通常会根据 `requirements.txt` 自动安装。

如果需要手动安装依赖，可在 AstrBot 环境中执行：

```bash
pip install -r data/plugins/astrbot_plugin_hindsight_memory/requirements.txt
```

## 命令

- `/hindsight status`：检查配置完整性和 Hindsight Cloud 连通性。
- `/hindsight recall <query>`：在当前会话 scope 下手动检索记忆。
- `/hindsight on`：启用当前会话记忆。
- `/hindsight off`：关闭当前会话记忆。
- `/hindsight help`：显示命令帮助。

`/hindsight on` 和 `/hindsight off` 的状态保存在 AstrBot 插件数据目录中，只影响当前会话 scope，不会修改 Hindsight Cloud 中已有的记忆。

## Scope 隔离策略

私聊使用以下 tags：

```text
scope:private
platform:<platform_id>
sender:<sender_id_hash>
umo:<umo_hash>
```

群聊使用以下 tags：

```text
scope:group
platform:<platform_id>
group:<group_id_hash>
umo:<umo_hash>
```

召回时固定使用 `tags_match: all_strict`，因此私聊只召回当前私聊 scope 的记忆，群聊只召回当前群聊 scope 的记忆。

## ID 稳定性与迁移注意事项

正常重启 AstrBot 通常不会改变记忆 scope。插件生成 tags 时会使用：

- `platform_id`：AstrBot 平台名，例如 `aiocqhttp`、`qq_official`。
- `sender_id`：平台提供的用户 ID。
- `group_id`：平台提供的群 ID。
- `unified_msg_origin`：AstrBot 的会话来源标识。
- 本地 `salt`：插件首次运行时生成，并保存在 AstrBot 插件数据目录中。

只要平台适配器、机器人账号和插件数据目录不变，重启后 hash 出来的 tags 应保持稳定，旧记忆可以继续召回。

以下情况可能导致同一个用户或群生成不同 scope，从而召回不到旧记忆：

- 删除或迁移时丢失插件数据目录，导致 `salt.txt` 重新生成。
- 更换平台适配器，例如从 `aiocqhttp` 切换到 `qq_official`。
- 更换机器人账号、QQ 官方应用或平台配置，导致平台侧用户 ID 变化。
- 平台或 AstrBot 适配器更新后改变了 `sender_id`、`group_id`、`unified_msg_origin` 的生成方式。
- 群聊事件暂时拿不到 `group_id`，插件会降级为私聊 scope；之后如果又能拿到 `group_id`，scope 会发生变化。

迁移 AstrBot 或插件时，建议同时备份插件数据目录中的 `salt.txt` 和 `scope_state.json`。其中 `salt.txt` 会影响历史记忆是否还能被同一 scope 召回，`scope_state.json` 保存 `/hindsight on` 和 `/hindsight off` 的当前会话开关状态。

## Hindsight API

插件直接调用 Hindsight Cloud REST API，不依赖官方 SDK：

- Recall：`POST /v1/default/banks/{bank_id}/memories/recall`
- Retain：`POST /v1/default/banks/{bank_id}/memories`
- 状态检查：`GET /v1/default/banks/{bank_id}/tags?limit=1`

Retain 使用 item-level `tags`，并固定使用 `async: true`，减少对聊天流程延迟的影响。

## 测试方法

### 本地单元测试

在仓库根目录执行：

```bash
python -m unittest discover -s tests
```

### 语法检查

```bash
python -m py_compile main.py commands.py hindsight_client.py memory_formatter.py scope.py
```

### AstrBot 手动验收

1. 在 AstrBot WebUI 中确认插件已启用，且 `api_key`、`bank_id` 已配置。
2. 在聊天中发送：

   ```text
   /hindsight status
   ```

   期望看到配置完整，并且 Hindsight Cloud 连接正常。

3. 发送一条需要记忆的内容，例如：

   ```text
   我最喜欢的饮料是冰美式，请记住。
   ```

4. 等待几秒到几十秒后，再问：

   ```text
   我最喜欢喝什么？
   ```

   如果 Hindsight 已完成异步处理，模型应能通过 recall 回答出相关记忆。

5. 测试当前会话开关：

   ```text
   /hindsight off
   /hindsight on
   ```

6. 在不同私聊、不同群聊之间分别测试，确认记忆不会跨 scope 召回。
