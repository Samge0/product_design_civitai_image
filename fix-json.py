"""
修复缺失的 JSON 文件
从 Civitai 页面获取图片信息并生成对应的 JSON 文件
"""
import os
import re
import json
import time
import logging
from pathlib import Path
from typing import Dict, Optional
import requests
from fake_useragent import UserAgent
from bs4 import BeautifulSoup

from civitai_crawler import CivitaiCrawler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class JsonFixer(CivitaiCrawler):
    """修复缺失 JSON 文件的工具类"""

    def __init__(self):
        super().__init__()
        self.ua = UserAgent()

    def _extract_id_from_filename(self, filename: str) -> Optional[str]:
        """
        从文件名中提取 Civitai 图片 ID
        文件名格式: {年份}_{id}_{其他值}.{ext}
        例如: 2025_57772184_uuid.jpg -> 57772184
        """
        # 匹配格式: 数字_数字_其他内容
        match = re.match(r'^(\d+)_(\d+)_(.+)$', Path(filename).stem)
        if match:
            year, image_id, _ = match.groups()
            logger.debug(f"从文件名 {filename} 提取到 ID: {image_id}")
            return image_id

        # 尝试另一种格式: 只包含 id_uuid
        match2 = re.match(r'^(\d+)_(.+)$', Path(filename).stem)
        if match2:
            image_id, _ = match2.groups()
            # 验证是否为有效的数字ID
            if image_id.isdigit() and len(image_id) >= 5:
                logger.debug(f"从文件名 {filename} 提取到 ID: {image_id}")
                return image_id

        logger.warning(f"无法从文件名 {filename} 提取 ID")
        return None

    def _fetch_page_data(self, image_id: str) -> Optional[Dict]:
        """
        从 Civitai 图片页面获取数据
        返回: 提取的 JSON 数据，如果失败返回 None

        实际 JSON 结构:
        props.pageProps.trpcState.json.queries[0].state.data
        """
        url = f"https://civitai.com/images/{image_id}"
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            logger.info(f"正在获取页面数据: {url}")
            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=30)
            response.raise_for_status()

            # 解析 HTML，提取 __NEXT_DATA__ 脚本内容
            soup = BeautifulSoup(response.text, 'html.parser')
            next_data_script = soup.find('script', {'id': '__NEXT_DATA__'})

            if not next_data_script:
                logger.error(f"未找到 __NEXT_DATA__ 脚本标签，ID: {image_id}")
                return None

            # 解析 JSON 数据
            next_data = json.loads(next_data_script.string)

            # 从页面数据中提取图片信息
            # 实际路径: props.pageProps.trpcState.json.queries[0].state.data
            page_props = next_data.get('props', {}).get('pageProps', {})
            trpc_state = page_props.get('trpcState', {})
            trpc_json = trpc_state.get('json', {})
            queries = trpc_json.get('queries', [])

            # 找到包含图片数据的 query (通常是第一个，且包含 id 字段)
            image_data = None
            for query in queries:
                state_data = query.get('state', {}).get('data')
                if state_data and isinstance(state_data, dict) and 'id' in state_data:
                    image_data = state_data
                    break

            if not image_data:
                logger.error(f"页面数据中未找到图片信息，ID: {image_id}")
                # 调试: 打印 queries 结构
                logger.debug(f"Queries 数量: {len(queries)}")
                for i, q in enumerate(queries):
                    query_key = q.get('queryKey', [])
                    logger.debug(f"Query {i}: {query_key}")
                return None

            return image_data

        except requests.RequestException as e:
            logger.error(f"请求页面失败: {e}, ID: {image_id}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"解析 JSON 数据失败: {e}, ID: {image_id}")
            return None
        except Exception as e:
            logger.error(f"获取页面数据时出错: {e}, ID: {image_id}")
            return None

    def _fetch_image_from_api(self, post_id: str) -> Optional[Dict]:
        """
        通过 API 获取完整的图片数据
        API: https://civitai.com/api/v1/images?limit=1&postId={postId}&t=时间戳

        返回完整的图片数据对象，包含:
        - prompt (从 meta.prompt)
        - baseModel
        - workflow (可作为 generationProcess)
        - 以及其他字段
        """
        url = f"https://civitai.com/api/v1/images"
        params = {
            "limit": 1,
            "postId": post_id,
            "t": int(time.time() * 1000)
        }
        headers = {
            "User-Agent": self.ua.random,
            "Authorization": self.auth_token
        }

        try:
            logger.debug(f"正在获取 API 数据: postId={post_id}")
            response = requests.get(url, params=params, headers=headers, proxies=self.proxies, timeout=30)
            response.raise_for_status()

            data = response.json()
            items = data.get("items", [])

            if not items:
                logger.warning(f"API 返回空数据，postId: {post_id}")
                return None

            logger.debug(f"成功获取 API 数据")
            return items[0]

        except requests.RequestException as e:
            logger.error(f"请求 API 失败: {e}, postId: {post_id}")
            return None
        except Exception as e:
            logger.error(f"获取 API 数据时出错: {e}, postId: {post_id}")
            return None

    def _extract_json_fields(self, page_data: Dict, api_data: Optional[Dict] = None) -> Dict:
        """
        合并页面数据和 API 数据，提取需要的 JSON 字段

        Args:
            page_data: 从 __NEXT_DATA__ 提取的页面数据
            api_data: 从 API 获取的完整数据（可选）
        """
        user = page_data.get("user", {}) or {}

        # 计算 aspectRatio 方向
        aspect_ratio = page_data.get("aspectRatio", "")
        if not aspect_ratio:
            width = page_data.get("width") or (api_data.get("width") if api_data else None)
            height = page_data.get("height") or (api_data.get("height") if api_data else None)
            if width and height:
                w, h = int(width), int(height)
                # 根据宽高比例确定方向
                if w > h:
                    aspect_ratio = "Landscape"
                elif w < h:
                    aspect_ratio = "Portrait"
                else:
                    aspect_ratio = "Square"
            else:
                aspect_ratio = "Unknown"

        # 从 API 数据获取额外字段（如果可用）
        meta = (api_data or {}).get("meta", {}) or {}
        prompt = meta.get("prompt", "") or ""
        base_model = (api_data or {}).get("baseModel", "") or ""
        generation_process = meta.get("workflow", "") or ""

        # 获取 name (优先使用页面数据，其次 API 数据的 name 或生成的 name)
        name = page_data.get("name", "")
        if not name and api_data:
            # API 数据没有 name 字段，可以生成一个或留空
            name = ""

        json_data = {
            "id": page_data.get("id"),
            "postId": page_data.get("postId"),
            "prompt": prompt,
            "type": page_data.get("type", ""),
            "generationProcess": generation_process,
            "createdAt": page_data.get("createdAt", ""),
            "name": name,
            "aspectRatio": aspect_ratio,
            "user": {
                "id": user.get("id"),
                "username": user.get("username", "")
            },
            "baseModel": base_model,
        }

        return json_data

    def fix_missing_json(self, limit: int = None, start_index: int = 0):
        """
        修复缺失的 JSON 文件

        Args:
            limit: 最多修复的文件数，None 表示全部修复
            start_index: 从第几个缺失文件开始（用于断点续传）
        """
        logger.info("=" * 60)
        logger.info("开始修复缺失的 JSON 文件")
        logger.info("=" * 60)
        logger.info(f"目标目录: {self.image_dir}")

        # 获取所有图片文件（排除 .backup 目录）
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        image_files = [
            f for f in self.image_dir.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        ]

        if not image_files:
            logger.info("没有找到图片文件")
            return

        # 找出缺失 JSON 的图片
        missing_json_images = []
        for image_file in image_files:
            json_file = image_file.with_suffix(".json")
            if not json_file.exists():
                missing_json_images.append(image_file)

        if not missing_json_images:
            logger.info("没有缺失 JSON 的图片")
            return

        total_missing = len(missing_json_images)
        logger.info(f"发现 {total_missing} 个缺失 JSON 的图片")

        # 应用 start_index
        if start_index > 0:
            if start_index >= total_missing:
                logger.warning(f"start_index ({start_index}) 大于总数量 ({total_missing})")
                return
            missing_json_images = missing_json_images[start_index:]
            logger.info(f"从第 {start_index} 个文件开始修复")

        # 应用 limit
        if limit:
            missing_json_images = missing_json_images[:limit]
            logger.info(f"本次修复数量: {len(missing_json_images)}")

        success_count = 0
        fail_count = 0
        skipped_count = 0

        for idx, image_file in enumerate(missing_json_images, 1):
            logger.info(f"\n[{idx}/{len(missing_json_images)}] 处理: {image_file.name}")

            # 提取 ID
            image_id = self._extract_id_from_filename(image_file.name)
            if not image_id:
                logger.warning(f"跳过: 无法提取 ID")
                skipped_count += 1
                continue

            # 获取页面数据
            page_data = self._fetch_page_data(image_id)
            if not page_data:
                logger.warning(f"跳过: 无法获取页面数据")
                fail_count += 1
                continue

            # 获取 API 数据（包含 prompt, baseModel 等）
            post_id = page_data.get("postId")
            api_data = None
            if post_id:
                api_data = self._fetch_image_from_api(post_id)
                if not api_data:
                    logger.warning(f"未能获取 API 数据，部分字段将为空")
            else:
                logger.warning(f"未找到 postId，无法获取 API 数据")

            # 提取 JSON 字段（合并页面数据和 API 数据）
            json_data = self._extract_json_fields(page_data, api_data)

            # 保存 JSON 文件
            json_path = image_file.with_suffix(".json")
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
                logger.info(f"成功: JSON 已保存")
                success_count += 1
            except Exception as e:
                logger.error(f"保存 JSON 失败: {e}")
                fail_count += 1

            # 避免请求过快
            time.sleep(1)

        # 打印总结
        logger.info("=" * 60)
        logger.info("修复完成")
        logger.info(f"总缺失数: {total_missing}")
        logger.info(f"本次处理: {len(missing_json_images)}")
        logger.info(f"成功: {success_count}")
        logger.info(f"失败: {fail_count}")
        logger.info(f"跳过: {skipped_count}")
        logger.info("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="修复缺失的 JSON 文件")
    parser.add_argument("--limit", type=int, default=None, help="最多修复的文件数")
    parser.add_argument("--start", type=int, default=0, help="从第几个文件开始（用于断点续传）")
    args = parser.parse_args()

    fixer = JsonFixer()
    fixer.fix_missing_json(limit=args.limit, start_index=args.start)
