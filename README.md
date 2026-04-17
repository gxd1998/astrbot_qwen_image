# astrbot_plugin_qwen_image

基于阿里云通义万相 [qwen-image-2.0](https://help.aliyun.com/zh/model-studio/qwen-image-api) 模型的 AI 绘图插件，适配 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 框架。

## 功能

- **文生图** — 通过文本描述生成图片
- **图生图** — 基于参考图 + 文本描述生成新图片
- **LLM Tool** — 注册为 AI 工具，支持 AI 自动调用绘图能力

## 安装

### 方式一：从插件市场安装

在 AstrBot WebUI 的插件市场中搜索 `Qwen Image` 安装。

### 方式二：本地安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/gxd1998/astrbot_qwen_image.git
```

然后重启 AstrBot 或在 WebUI 插件管理页面重载插件。

## 配置

在 AstrBot WebUI → 插件管理 → Qwen Image → 配置 中设置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| API Key | 阿里云 DashScope API Key（留空则读取环境变量 `DASHSCOPE_API_KEY`） | 空 |
| 模型名称 | 图像生成模型 | `qwen-image-2.0` |
| 图片尺寸 | 生成图片的尺寸 | `1024*1024` |
| 图片质量 | 生成质量 | `standard` |
| 超时时间 | API 请求超时（秒） | `120` |
| 负面提示词 | 不希望出现的内容 | 空 |

## 使用方法

### 命令调用

| 命令 | 说明 | 示例 |
|------|------|------|
| `/qwen文生图 <描述>` | 文本生成图片 | `/qwen文生图 一只橘猫坐在窗台上` |
| `/qwen图生图 <描述>` | 带参考图生成（需先发送图片） | 发送图片 + `/qwen图生图 换成海滩背景` |
| `/qwen图片帮助` | 显示帮助信息 | — |

### LLM Tool 调用

插件会自动注册为 LLM Tool（`qwen_generate_image`），AI 可以在对话中自动调用绘图功能。例如：

> 用户：帮我画一只在海边看日落的猫
> AI：好的，我来为你生成这张图片。（自动调用 qwen-image-2.0）

## 依赖

- Python >= 3.10
- [dashscope](https://github.com/aliyun/alibabacloud-bailian-python-sdk) >= 1.17.0
- httpx >= 0.24.0

## 相关链接

- [AstrBot 官方仓库](https://github.com/AstrBotDevs/AstrBot)
- [qwen-image-2.0 API 文档](https://help.aliyun.com/zh/model-studio/qwen-image-api)
- [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)

## 许可证

MIT License
