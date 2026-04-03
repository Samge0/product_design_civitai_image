"""
Civitai图片爬虫 - 抓取产品设计和工业设计相关图片
使用 curl 命令行工具下载图片
"""
import os
import time
import argparse
import json
import subprocess
import requests
from pathlib import Path
from typing import List, Dict
from fake_useragent import UserAgent
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

# 加载环境变量
load_dotenv()


class CivitaiCrawler:

    def __init__(self):
        self.ua = UserAgent()
        self.api_url = "https://search-new.civitai.com/multi-search"
        self.auth_token = f"Bearer 8c46eb2508e21db1e9828a97968d91ab1ca1caa5f70a00e88a2ba1e286603b61"

        # 使用 Session 保持会话
        self.session = requests.Session()

        # 从环境变量读取代理配置
        _proxy = os.getenv("PROXY")
        if _proxy:
            _proxy_str = f"http://{_proxy}"
            self.session.proxies = {"http": _proxy_str, "https": _proxy_str}
            self.proxies = {"http": _proxy_str, "https": _proxy_str}
        else:
            self.proxies = None

        # 从环境变量读取代理配置
        _proxy = os.getenv("PROXY")
        if _proxy:
            _proxy_str = f"http://{_proxy}"
            self.proxies = {"http": _proxy_str, "https": _proxy_str}
        else:
            self.proxies = None
            
        self.target_years = [2025]
        self.download_interval = 2  # 下载间隔（秒）
        self.include_keywords = ["industrial design", "product design", "product rendering"]
        self.exclude_keywords = ["anime", "cartoon", "fanart", "nsfw", "portrait", "fashion",
                                 "character", "woman", "man", "girl", "boy", "person", "human"]
        self.image_dir = Path("./.cache/civitai_com_image_results")
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.fail_ids_file = Path("./.cache/fail_ids")
        self.fail_ids_file.parent.mkdir(parents=True, exist_ok=True)

    def _get_fail_ids(self) -> set:
        """读取失败的id列表"""
        if not self.fail_ids_file.exists():
            return set()
        with open(self.fail_ids_file, 'r') as f:
            return set(line.strip() for line in f if line.strip())

    def _add_fail_id(self, item_id: str):
        """添加失败的id"""
        fail_ids = self._get_fail_ids()
        fail_ids.add(str(item_id))
        with open(self.fail_ids_file, 'w') as f:
            f.write('\n'.join(fail_ids))

    def _remove_fail_id(self, item_id: str):
        """移除已成功下载的id"""
        fail_ids = self._get_fail_ids()
        fail_ids.discard(str(item_id))
        with open(self.fail_ids_file, 'w') as f:
            f.write('\n'.join(fail_ids))

    def _get_headers(self) -> Dict[str, str]:
        return {"user-agent": self.ua.random, "authorization": self.auth_token}

    def _should_include(self, item: Dict) -> bool:
        """检查item是否符合条件"""
        prompt = item.get("prompt", "").lower()
        created_at = item.get("createdAt", "")

        # 必须包含至少一个包含关键词
        if not any(kw in prompt for kw in self.include_keywords):
            return False
        # 不能包含任何排除关键词
        if any(kw in prompt for kw in self.exclude_keywords):
            return False
        # 年份过滤
        if created_at and int(created_at[:4]) not in self.target_years:
            return False
        return True

    def _fetch_page(self, offset: int, limit: int = 51) -> List[Dict]:
        """获取一页数据"""
        body = {
            "queries": [{
                "q": "product design",
                "indexUid": "images_v6",
                "facets": ["aspectRatio", "baseModel", "createdAtUnix", "tagNames",
                          "techniqueNames", "toolNames", "type", "user.username"],
                "attributesToHighlight": [],
                "highlightPreTag": "__ais-highlight__",
                "highlightPostTag": "__ais-highlight__",
                "limit": limit,
                "offset": offset,
                "filter": ["(poi != true) AND (NOT (nsfwLevel IN [4, 8, 16, 32] AND baseModel IN "
                          "['SD 3', 'SD 3.5', 'SD 3.5 Medium', 'SD 3.5 Large', 'SD 3.5 Large Turbo', "
                          "'SDXL Turbo', 'SVD', 'SVD XT', 'Stable Cascade'])) AND (nsfwLevel=1)"]
            }]
        }
        try:
            response = requests.post(
                self.api_url, json=body, headers=self._get_headers(),
                proxies=self.proxies, timeout=30
            )
            response.raise_for_status()
            hits = response.json().get("results", [{}])[0].get("hits", [])
            return [item for item in hits if self._should_include(item)], hits
        except requests.RequestException as e:
            print(f"请求失败: {e}")
            return [], []

    def _validate_image(self, path: Path) -> tuple[bool, str]:
        """
        验证下载的图片完整性
        返回: (是否有效, 错误信息)
        """
        try:
            # 检查文件大小
            file_size = path.stat().st_size
            if file_size == 0:
                return False, "文件大小为0"

            # 最小图片大小检查（防止损坏的微型文件）
            min_size = 1024  # 1KB
            if file_size < min_size:
                return False, f"文件过小 ({file_size} bytes)"

            # 尝试打开并验证图片
            with Image.open(path) as img:
                # 验证图片可以正常加载
                img.verify()

            # verify()会关闭文件，需要重新打开检查
            with Image.open(path) as img:
                # 检查图片尺寸是否有效
                width, height = img.size
                if width < 1 or height < 1:
                    return False, f"无效的图片尺寸 ({width}x{height})"

                # 尝试加载像素数据（确保图片数据完整）
                img.load()

            return True, ""

        except UnidentifiedImageError:
            return False, "无法识别的图片格式"
        except OSError as e:
            return False, f"图片损坏: {str(e)}"
        except Exception as e:
            return False, f"验证失败: {str(e)}"

    def _download_with_curl(self, url: str, path: Path) -> bool:
        """使用 curl 命令行工具下载图片"""
        try:
            cmd = [
                "curl",
                f"-Huser-agent: {self.ua.random}",
                f"-Hauthorization: {self.auth_token}",
                "-Hreferer: https://civitai.com/",
                "-Haccept: image/*",
                "-L",  # 跟随重定向
                "-s",  # 静默模式
                "-k",  # 跳过证书验证
                "-o", str(path),
                url,
            ]

            # 添加代理
            if self.proxies:
                proxy_url = self.proxies.get("https") or self.proxies.get("http")
                if proxy_url:
                    cmd.insert(-1, "-x")
                    cmd.insert(-1, proxy_url)

            result = subprocess.run(cmd, capture_output=True, timeout=60)

            if result.returncode == 0 and path.exists() and path.stat().st_size > 0:
                return True
            else:
                print(f"  [curl] 下载失败 (return code: {result.returncode})")
                if result.stderr:
                    error_msg = result.stderr.decode('utf-8', errors='ignore')
                    if '401' in error_msg:
                        print(f"  [curl] 认证失败 (401)")
                    else:
                        print(f"  [curl] 错误: {error_msg[:200]}")
                        
                time.sleep(0.5)
                
                return False
        except FileNotFoundError:
            print("  [curl] 未安装 curl")
            return False
        except Exception as e:
            print(f"  [curl] 失败: {e}")
            return False

    def _save_item(self, item: Dict) -> bool:
        """保存单个item（图片+json）"""
        url = item.get("url", "")
        item_id = item.get("id")
        created_at = item.get("createdAt", "")
        year = created_at[:4] if created_at else "unknown"

        base_name = os.path.splitext(url.rstrip("/").split("/")[-1])[0]
        ext = os.path.splitext(url.rstrip("/").split("/")[-1])[1] or ".jpg"

        # 文件名添加年份前缀
        filename = f"{year}_{base_name}"
        image_path = self.image_dir / f"{filename}{ext}"
        json_path = self.image_dir / f"{filename}.json"

        # 检查文件是否已存在
        if image_path.exists() and json_path.exists():
            return False  # 已存在，跳过

        # 构建图片 URL
        image_url = f"https://image-b2.civitai.com/file/civitai-media-cache/{url}/original"

        # 使用 curl 下载图片
        print(f"  下载中...", end=" ")
        if not self._download_with_curl(image_url, image_path):
            self._add_fail_id(item_id)
            print(f"下载失败: ID={item_id}")
            return False

        # 验证图片完整性
        is_valid, error_msg = self._validate_image(image_path)
        if not is_valid:
            # 删除损坏的文件
            if image_path.exists():
                image_path.unlink()
            self._add_fail_id(item_id)
            print(f"校验失败: {error_msg}, ID={item_id} \n 下载地址: {image_url} \n 详情地址: https://civitai.com/images/{item_id} \n")
            time.sleep(0.5)
            return False

        print("成功!")

        # 保存json
        json_data = {
            "id": item.get("id"),
            "prompt": item.get("prompt", ""),
            "createdAt": item.get("createdAt", ""),
            "url": url,
            "aspectRatio": item.get("aspectRatio", ""),
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        # 成功后从失败列表移除
        self._remove_fail_id(item_id)
        return True

    def crawl(self, max_pages: int = None, items_per_page: int = 51):
        """爬取数据并下载图片"""
        print(f"开始爬取 Civitai 图片...")
        print(f"目标年份: {self.target_years}")
        print(f"关键词: {self.include_keywords}")

        offset = 0
        page_count = 0
        total_found = 0
        total_downloaded = 0

        while True:
            if max_pages and page_count >= max_pages:
                break

            items, hits = self._fetch_page(offset, items_per_page)
            
            if not hits:
                print("没有更多数据")
                break
            
            if not items:
                continue

            page_count += 1
            offset += items_per_page
            total_found += len(items)

            # 下载
            downloaded = sum(1 for item in items if self._save_item(item))
            skipped = len(items) - downloaded
            total_downloaded += downloaded

            print(f"第{page_count}页: 找到{len(items)}条, 下载{downloaded}张, 跳过{skipped}张")
            time.sleep(self.download_interval)

        print(f"\n完成! 共找到{total_found}条, 下载{total_downloaded}张")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Civitai图片爬虫")
    parser.add_argument("--max-pages", type=int, default=None, help="最大爬取页数")
    args = parser.parse_args()

    CivitaiCrawler().crawl(max_pages=args.max_pages)
