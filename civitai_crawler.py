"""
Civitai图片爬虫 - 抓取产品设计和工业设计相关图片
"""
import os
import sqlite3
import time
import random
import argparse
import requests
from pathlib import Path
from typing import List, Dict, Set

# 数据库路径
DB_PATH = "./.cache/civitai_images.db"


class CivitaiCrawler:
    # 随机User-Agent列表
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    ]

    def __init__(self, db_path: str = DB_PATH):
        """初始化爬虫"""
        self.db_path = db_path
        self.api_url = "https://search-new.civitai.com/multi-search"
        self.auth_token = f"Bearer 8c46eb2508e21db1e9828a97968d91ab1ca1caa5f70a00e88a2ba1e286603b61"

        # 代理配置
        self.proxy = "http://127.0.0.1:7890"
        self.proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

        # 年份过滤（只抓取2025年的数据）
        self.target_year = 2025

        # 关键词过滤配置
        self.include_keywords = ["industrial design", "product design", "product rendering"]
        self.exclude_keywords = ["anime", "cartoon", "fanart", "nsfw", "portrait", "fashion",
                                 "character", "woman", "man", "girl", "boy", "person", "human"]

        # 图片保存目录
        self.image_dir = Path("./.cache/civitai_com_image_results")
        self.image_dir.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _get_headers(self) -> Dict[str, str]:
        """获取带有随机User-Agent的请求头"""
        return {
            "user-agent": random.choice(self.USER_AGENTS),
            "authorization": self.auth_token
        }

    def _init_db(self):
        """初始化SQLite数据库"""
        # 确保数据库目录存在
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                prompt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                url TEXT NOT NULL,
                image_path TEXT,
                downloaded INTEGER DEFAULT 0,
                UNIQUE(id)
            )
        """)

        conn.commit()
        conn.close()

    def _should_include_prompt(self, prompt: str) -> bool:
        """
        检查prompt是否应该被包含
        必须包含至少一个include关键词，且不能包含任何exclude关键词
        """
        if not prompt:
            return False

        prompt_lower = prompt.lower()

        # 检查是否包含至少一个必需关键词
        has_include = any(kw in prompt_lower for kw in self.include_keywords)
        if not has_include:
            return False

        # 检查是否包含排除关键词
        has_exclude = any(kw in prompt_lower for kw in self.exclude_keywords)
        if has_exclude:
            return False

        return True

    def _should_include_year(self, created_at: str) -> bool:
        """检查是否为目标年份的数据"""
        if not created_at:
            return False
        # createdAt格式: "2025-06-13T01:20:38.384Z"
        return created_at.startswith(str(self.target_year))

    def _save_to_db(self, items: List[Dict]) -> tuple[int, int]:
        """
        保存数据到数据库
        :return: (新增数量, 跳过数量)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        saved_count = 0
        skipped_count = 0
        for item in items:
            item_id = item.get("id")
            prompt = item.get("prompt", "")
            created_at = item.get("createdAt", "")
            url = item.get("url", "")

            try:
                cursor.execute(
                    """INSERT OR IGNORE INTO images (id, prompt, created_at, url)
                       VALUES (?, ?, ?, ?)""",
                    (item_id, prompt, created_at, url)
                )
                if cursor.rowcount > 0:
                    saved_count += 1
                else:
                    skipped_count += 1
            except sqlite3.Error as e:
                print(f"保存数据失败 (ID: {item_id}): {e}")

        conn.commit()
        conn.close()
        return saved_count, skipped_count

    def _build_request_body(self, offset: int, limit: int = 51) -> Dict:
        """构建请求体"""
        return {
            "queries": [{
                "q": "product design",
                "indexUid": "images_v6",
                "facets": [
                    "aspectRatio", "baseModel", "createdAtUnix", "tagNames",
                    "techniqueNames", "toolNames", "type", "user.username"
                ],
                "attributesToHighlight": [],
                "highlightPreTag": "__ais-highlight__",
                "highlightPostTag": "__ais-highlight__",
                "limit": limit,
                "offset": offset,
                "filter": [
                    "(poi != true) AND (NOT (nsfwLevel IN [4, 8, 16, 32] AND baseModel IN "
                    "['SD 3', 'SD 3.5', 'SD 3.5 Medium', 'SD 3.5 Large', 'SD 3.5 Large Turbo', "
                    "'SDXL Turbo', 'SVD', 'SVD XT', 'Stable Cascade'])) AND (nsfwLevel=1)"
                ]
            }]
        }

    def fetch_page(self, offset: int = 0, limit: int = 51) -> List[Dict]:
        """
        获取一页数据
        返回通过prompt过滤后的item列表
        """
        try:
            print(f"正在爬取: offset={offset}, limit={limit}")
            response = requests.post(
                self.api_url,
                json=self._build_request_body(offset, limit),
                headers=self._get_headers(),
                proxies=self.proxies,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            hits = data.get("results", [{}])[0].get("hits", [])

            # 过滤prompt和年份
            filtered_items = []
            for item in hits:
                if not self._should_include_prompt(item.get("prompt", "")):
                    continue
                if not self._should_include_year(item.get("createdAt", "")):
                    continue
                filtered_items.append(item)

            print(f"页码偏移 {offset}: 获取 {len(hits)} 条，过滤后 {len(filtered_items)} 条")

            return filtered_items, hits

        except requests.RequestException as e:
            print(f"请求失败 (offset={offset}): {e}")
            return [], []

    def _download_items(self, items: List[Dict]) -> tuple[int, int, int]:
        """
        下载指定列表中的图片
        :return: (成功数量, 失败数量, 跳过数量)
        """
        if not items:
            return 0, 0, 0

        success_count = 0
        failed_count = 0
        skipped_count = 0

        for item in items:
            item_id = item.get("id")
            url = item.get("url", "")

            # 检查图片文件是否已存在
            ext = os.path.splitext(url.split("/")[-1])[1] or ".jpg"
            save_path = self.image_dir / f"{item_id}{ext}"

            if save_path.exists():
                # 文件已存在，跳过下载
                skipped_count += 1
                continue

            image_url = self.get_image_url(url)
            if self.download_image(image_url, save_path):
                self._update_download_status(item_id, str(save_path))
                success_count += 1
            else:
                failed_count += 1

            time.sleep(0.1)

        return success_count, failed_count, skipped_count

    def _update_download_status(self, item_id: int, image_path: str):
        """更新图片下载状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE images SET image_path = ?, downloaded = 1 WHERE id = ?",
            (image_path, item_id)
        )
        conn.commit()
        conn.close()

    def crawl(self, max_pages: int = None, items_per_page: int = 51, download_images: bool = True):
        """
        爬取数据
        :param max_pages: 最大爬取页数，None表示无限翻页直到没有新数据
        :param items_per_page: 每页条数
        :param download_images: 是否边爬取边下载图片，默认True
        """
        print(f"开始爬取 Civitai 图片数据...")
        print(f"目标年份: {self.target_year}")
        print(f"包含关键词: {self.include_keywords}")
        print(f"排除关键词: {self.exclude_keywords}")
        print(f"边爬取边下载: {'是' if download_images else '否'}")

        offset = 0
        page_count = 0
        total_saved = 0
        total_downloaded = 0

        while True:
            if max_pages and page_count >= max_pages:
                print(f"已达到最大页数限制: {max_pages}")
                break

            items, hits = self.fetch_page(offset, items_per_page)

            if not hits:
                print("没有更多数据，爬取结束")
                break

            page_count += 1
            offset += items_per_page

            if not items:
                print(f"第 {page_count} 页: 过滤后无符合条件的数据，跳过")
                continue

            # 保存到数据库
            saved, duplicate = self._save_to_db(items)
            total_saved += saved

            # 下载图片
            downloaded = 0
            failed = 0
            skipped = 0
            if download_images:
                downloaded, failed, skipped = self._download_items(items)
                total_downloaded += downloaded

            status_parts = [f"新增 {saved} 条"]
            if duplicate > 0:
                status_parts.append(f"重复 {duplicate} 条")
            if download_images:
                status_parts.append(f"下载 {downloaded} 张")
                if failed > 0:
                    status_parts.append(f"失败 {failed} 张")
                if skipped > 0:
                    status_parts.append(f"跳过 {skipped} 张")
            print(f"第 {page_count} 页: {', '.join(status_parts)}，累计新增 {total_saved} 条")

            # 避免请求过快
            time.sleep(0.3)

        print(f"\n爬取完成! 共保存 {total_saved} 条数据，下载 {total_downloaded} 张图片")

    def get_image_url(self, url: str) -> str:
        """构建完整的图片URL"""
        return f"https://image-b2.civitai.com/file/civitai-media-cache/{url}/450x%3Cauto%3E_so"

    def download_image(self, url: str, save_path: str) -> bool:
        """下载单张图片"""
        try:
            response = requests.get(url, headers=self._get_headers(), proxies=self.proxies, timeout=30)
            response.raise_for_status()

            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True

        except Exception as e:
            print(f"下载失败 {url}: {e}")
            return False

    def download_all_images(self):
        """下载所有未下载的图片"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id, url, downloaded FROM images WHERE downloaded = 0")
        items = cursor.fetchall()

        if not items:
            print("没有需要下载的图片")
            conn.close()
            return

        print(f"准备下载 {len(items)} 张图片...")
        success_count = 0

        for item_id, url, _ in items:
            image_url = self.get_image_url(url)
            # 使用id作为文件名，保持原始扩展名
            ext = os.path.splitext(url.split("/")[-1])[1] or ".jpg"
            save_path = self.image_dir / f"{item_id}{ext}"

            if self.download_image(image_url, save_path):
                cursor.execute(
                    "UPDATE images SET image_path = ?, downloaded = 1 WHERE id = ?",
                    (str(save_path), item_id)
                )
                success_count += 1
                print(f"[{success_count}/{len(items)}] 下载完成: {item_id}{ext}")

            time.sleep(0.2)  # 避免请求过快

        conn.commit()
        conn.close()
        print(f"\n下载完成! 成功下载 {success_count}/{len(items)} 张图片")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Civitai图片爬虫")
    parser.add_argument("--download-only", action="store_true", help="仅下载图片，不爬取新数据")
    parser.add_argument("--crawl-only", action="store_true", help="仅爬取数据，不下载图片")
    parser.add_argument("--max-pages", type=int, default=None, help="最大爬取页数，默认无限翻页")
    args = parser.parse_args()

    crawler = CivitaiCrawler()

    if args.download_only:
        # 仅下载图片
        print("模式: 仅下载图片")
        crawler.download_all_images()
    elif args.crawl_only:
        # 仅爬取数据
        print("模式: 仅爬取数据")
        crawler.crawl(max_pages=args.max_pages, items_per_page=51, download_images=False)
    else:
        # 默认：边爬取边下载
        print("模式: 边爬取边下载")
        crawler.crawl(max_pages=args.max_pages, items_per_page=51, download_images=True)
