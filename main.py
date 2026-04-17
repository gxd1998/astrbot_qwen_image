"""
AstrBot 插件 - Qwen Image 文生图/图生图

功能:
- /qwen文生图 <提示词> — 纯文本生成图片
- /qwen图生图 <提示词> — 带参考图生成（需附带图片）
- LLM Tool: qwen_generate_image — 让 AI 主动调用绘图
"""

import asyncio
import os
import time
from pathlib import Path

import httpx
from dashscope import MultiModalConversation

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, StarTools

# DashScope API 地址
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

# 默认模型
DEFAULT_MODEL = "qwen-image-2.0"

# 默认图片尺寸
DEFAULT_SIZE = "1024*1024"

# 支持的尺寸列表
SUPPORTED_SIZES = [
    "1024*1024",
    "768*1024",
    "1024*768",
    "1152*896",
    "896*1152",
    "1344*768",
    "768*1344",
    "1440*720",
    "720*1440",
    "1328*1328",
]


class QwenImagePlugin(Star):
    """Qwen Image 图像生成插件"""

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_qwen_image")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 确保图片输出目录存在
        self.output_dir = self.data_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_api_key(self) -> str:
        """获取 API Key：优先从插件配置读取，否则从环境变量读取"""
        key = str(self.config.get("api_key", "") or "").strip()
        if key:
            return key
        key = os.getenv("DASHSCOPE_API_KEY", "")
        if key:
            return key
        raise RuntimeError(
            "未配置 API Key。请在插件配置中填写 api_key，或设置环境变量 DASHSCOPE_API_KEY"
        )

    def _get_model(self) -> str:
        return str(self.config.get("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()

    def _get_size(self) -> str:
        return str(self.config.get("size", DEFAULT_SIZE) or DEFAULT_SIZE).strip()

    def _get_timeout(self) -> int:
        try:
            return max(10, min(300, int(self.config.get("timeout", 120) or 120)))
        except (TypeError, ValueError):
            return 120

    def _get_negative_prompt(self) -> str:
        return str(self.config.get("negative_prompt", "") or "").strip()

    def _get_max_concurrency(self) -> int:
        try:
            return max(1, min(10, int(self.config.get("max_concurrency", 2) or 2)))
        except (TypeError, ValueError):
            return 2

    async def _download_image(self, url: str, timeout: int = 60) -> Path:
        """下载图片到本地并返回路径"""
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        # 根据时间戳生成文件名
        timestamp = int(time.time() * 1000)
        save_path = self.output_dir / f"qwen_{timestamp}.png"
        save_path.write_bytes(resp.content)

        logger.info(
            "[QwenImage] 图片已保存: %s (%d bytes)", save_path, len(resp.content)
        )
        return save_path

    async def _generate_text2img(self, prompt: str, size: str = "") -> Path:
        """调用 DashScope API 进行文生图"""
        api_key = self._get_api_key()
        model = self._get_model()
        size = size or self._get_size()
        timeout = self._get_timeout()
        negative = self._get_negative_prompt()

        messages = [{"role": "user", "content": [{"text": prompt}]}]

        logger.info(
            "[QwenImage] 文生图请求: model=%s, size=%s, prompt=%s",
            model,
            size,
            prompt[:50],
        )

        t0 = time.time()

        # dashscope SDK 是同步的，放到线程池里执行避免阻塞
        response = await asyncio.to_thread(
            MultiModalConversation.call,
            api_key=api_key,
            model=model,
            messages=messages,
            result_format="message",
            stream=False,
            size=size,
            negative_prompt=negative,
        )

        elapsed = time.time() - t0
        logger.info("[QwenImage] API 响应耗时: %.2fs", elapsed)

        if response.status_code != 200:
            raise RuntimeError(
                f"API 调用失败 (HTTP {response.status_code}): "
                f"code={response.code}, msg={response.message}"
            )

        # 解析响应，提取第一张图片 URL
        choices = response.output.choices
        if not choices:
            raise RuntimeError("API 返回结果为空（无 choices）")

        content_list = choices[0].message.get("content", [])
        image_url = None
        for item in content_list:
            if "image" in item:
                image_url = item["image"]
                break

        if not image_url:
            raise RuntimeError("API 返回结果中未包含图片")

        return await self._download_image(image_url, timeout=timeout)

    async def _generate_img2img(
        self, prompt: str, image_urls: list[str], size: str = ""
    ) -> Path:
        """调用 DashScope API 进行图生图"""
        api_key = self._get_api_key()
        model = self._get_model()
        size = size or self._get_size()
        timeout = self._get_timeout()
        negative = self._get_negative_prompt()

        # 构建 messages，包含图片和文本提示
        content_parts = []
        for url in image_urls:
            content_parts.append({"image": url})
        content_parts.append({"text": prompt})

        messages = [{"role": "user", "content": content_parts}]

        logger.info(
            "[QwenImage] 图生图请求: model=%s, size=%s, images=%d, prompt=%s",
            model,
            size,
            len(image_urls),
            prompt[:50],
        )

        t0 = time.time()

        response = await asyncio.to_thread(
            MultiModalConversation.call,
            api_key=api_key,
            model=model,
            messages=messages,
            result_format="message",
            stream=False,
            size=size,
            negative_prompt=negative,
        )

        elapsed = time.time() - t0
        logger.info("[QwenImage] API 响应耗时: %.2fs", elapsed)

        if response.status_code != 200:
            raise RuntimeError(
                f"API 调用失败 (HTTP {response.status_code}): "
                f"code={response.code}, msg={response.message}"
            )

        choices = response.output.choices
        if not choices:
            raise RuntimeError("API 返回结果为空（无 choices）")

        content_list = choices[0].message.get("content", [])
        image_url = None
        for item in content_list:
            if "image" in item:
                image_url = item["image"]
                break

        if not image_url:
            raise RuntimeError("API 返回结果中未包含图片")

        return await self._download_image(image_url, timeout=timeout)

    def _extract_image_urls_from_event(self, event: AstrMessageEvent) -> list[str]:
        """从消息事件中提取图片 URL"""
        urls = []
        try:
            chain = event.get_messages()
        except Exception:
            return urls

        for seg in chain:
            if isinstance(seg, Image):
                # 尝试从 Image 组件获取 URL
                url = getattr(seg, "url", None) or getattr(seg, "file", None)
                if url and isinstance(url, str) and url.startswith(("http://", "https://")):
                    urls.append(url)
                else:
                    # 尝试用 getScaledUrl 之类的方法
                    try:
                        from astrbot.api.message_components import Image as ImgCls

                        saved = getattr(seg, "file", None) or getattr(seg, "path", None)
                        if saved and Path(saved).exists():
                            # 本地文件，DashScope 不支持本地路径，需要跳过
                            logger.warning(
                                "[QwenImage] 收到本地图片路径，DashScope 不支持本地文件输入，请发送网络图片"
                            )
                    except Exception:
                        pass

        return urls

    async def _send_image(self, event: AstrMessageEvent, image_path: Path):
        """发送图片给用户，带多重降级"""
        p = str(image_path)

        # 方式1: fromFileSystem
        try:
            await event.send(event.chain_result([Image.fromFileSystem(p)]))
            return
        except Exception as e:
            logger.debug("[QwenImage] fromFileSystem 失败: %s", e)

        # 方式2: fromBytes
        try:
            data = await asyncio.to_thread(image_path.read_bytes)
            await event.send(event.chain_result([Image.fromBytes(data)]))
            return
        except Exception as e:
            logger.debug("[QwenImage] fromBytes 失败: %s", e)

        # 方式3: 发送文件
        try:
            from astrbot.api.message_components import File

            await event.send(
                event.chain_result(
                    [File(name=image_path.name, file=p)]
                )
            )
            return
        except Exception as e:
            logger.debug("[QwenImage] File 发送也失败: %s", e)

        raise RuntimeError("所有图片发送方式均失败")

    # ==================== 命令处理 ====================

    @filter.command("qwen文生图", alias={"qwen画图", "qwen生图", "qwen绘图"})
    async def text2img_command(self, event: AstrMessageEvent, prompt: str):
        """使用通义千问生成图片

        用法: /qwen文生图 <提示词描述>
        示例: /qwen文生图 一只橘色猫咪坐在窗台上
        """
        prompt = (prompt or "").strip()
        if not prompt:
            yield event.plain_result("请提供图片描述提示词。\n用法: /qwen文生图 <提示词>")
            return

        try:
            yield event.plain_result("正在生成图片，请稍候...")
            image_path = await self._generate_text2img(prompt)
            await self._send_image(event, image_path)
            logger.info("[QwenImage] 文生图完成: %s", prompt[:30])
        except Exception as e:
            logger.error("[QwenImage] 文生图失败: %s", e)
            yield event.plain_result(f"生成失败: {e}")

    @filter.command("qwen图生图", alias={"qwen改图"})
    async def img2img_command(self, event: AstrMessageEvent, prompt: str):
        """使用通义千问编辑图片

        用法: /qwen图生图 <提示词> （需附带图片）
        示例: /qwen图生图 把背景换成海滩
        """
        prompt = (prompt or "").strip()
        if not prompt:
            yield event.plain_result("请提供编辑提示词。\n用法: /qwen图生图 <提示词> （需附带图片）")
            return

        # 提取消息中的图片 URL
        image_urls = self._extract_image_urls_from_event(event)
        if not image_urls:
            yield event.plain_result("未检测到图片。请发送图片后再使用此命令，或引用包含图片的消息。")
            return

        try:
            yield event.plain_result(f"正在编辑图片（共 {len(image_urls)} 张参考图），请稍候...")
            image_path = await self._generate_img2img(prompt, image_urls)
            await self._send_image(event, image_path)
            logger.info("[QwenImage] 图生图完成: %s", prompt[:30])
        except Exception as e:
            logger.error("[QwenImage] 图生图失败: %s", e)
            yield event.plain_result(f"编辑失败: {e}")

    # ==================== LLM Tool ====================

    @filter.llm_tool(name="qwen_generate_image")
    async def qwen_generate_image(
        self,
        event: AstrMessageEvent,
        prompt: str,
        mode: str = "auto",
        size: str = "",
    ):
        """使用通义千问 (Qwen Image) 生成图片。

        根据用户消息自动判断是文生图还是图生图：
        - 用户没有发送图片 → 纯文生图
        - 用户发送了图片 → 图生图/编辑图片

        Args:
            prompt(string): 图片描述提示词，需要详细描述画面内容、风格、构图等
            mode(string): auto=自动判断, text=强制文生图, edit=强制图生图
            size(string): 输出尺寸，如 1024*1024、768*1024 等，留空使用默认值
        """
        prompt = (prompt or "").strip()
        if not prompt:
            return "提示词不能为空，请提供图片描述。"

        m = (mode or "auto").strip().lower()
        size = (size or "").strip()

        # 尺寸校验
        if size and size not in SUPPORTED_SIZES:
            logger.warning(
                "[QwenImage] 不支持的尺寸 %s，将使用默认值 %s", size, self._get_size()
            )
            size = ""

        try:
            if m == "text":
                # 强制文生图
                image_path = await self._generate_text2img(prompt, size=size)
            elif m == "edit":
                # 强制图生图
                image_urls = self._extract_image_urls_from_event(event)
                if not image_urls:
                    return "图生图模式需要用户发送图片，但当前消息中没有检测到图片。请改用 mode=text 进行文生图。"
                image_path = await self._generate_img2img(prompt, image_urls, size=size)
            else:
                # 自动模式：检查消息中是否有图片
                image_urls = self._extract_image_urls_from_event(event)
                if image_urls:
                    image_path = await self._generate_img2img(prompt, image_urls, size=size)
                else:
                    image_path = await self._generate_text2img(prompt, size=size)

            # 发送图片给用户
            await self._send_image(event, image_path)

            return f"图片已生成并发送。提示词: {prompt[:50]}..."

        except Exception as e:
            logger.error("[QwenImage] LLM Tool 生成失败: %s", e)
            return f"图片生成失败: {e}"

    # ==================== 帮助命令 ====================

    @filter.command("qwen图片帮助")
    async def help_command(self, event: AstrMessageEvent):
        """显示 Qwen Image 插件帮助"""
        msg = """Qwen Image - 通义千问图像生成插件

== 命令 ==
/qwen文生图 <提示词> - 纯文本生成图片
/qwen图生图 <提示词> - 带图片生成（需附带图片）
/qwen图片帮助 - 显示本帮助

== LLM Tool ==
AI 会自动调用 qwen_generate_image 工具来生成图片

== 支持的尺寸 ==
1024*1024, 768*1024, 1024*768
1152*896, 896*1152, 1344*768
768*1344, 1440*720, 720*1440
1328*1328

== 配置 ==
在 WebUI 插件配置中可设置:
- api_key: DashScope API Key（也可用环境变量 DASHSCOPE_API_KEY）
- model: 模型名称（默认 qwen-image-2.0）
- size: 默认图片尺寸
- negative_prompt: 负面提示词
- timeout: 超时时间（秒）
"""
        yield event.plain_result(msg)

    # ==================== 生命周期 ====================

    async def initialize(self):
        """插件初始化"""
        model = self._get_model()
        logger.info(
            "[QwenImage] 插件初始化完成: model=%s, output_dir=%s",
            model,
            self.output_dir,
        )

    async def terminate(self):
        """插件卸载"""
        logger.info("[QwenImage] 插件已卸载")
