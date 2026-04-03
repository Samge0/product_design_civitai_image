"""
Civitai图片爬虫 - 抓取产品设计和工业设计相关图片
使用 requests 流式下载图片，支持动态获取 CDN key 和重试机制
"""
import os
import errno
import time
import argparse
import json
import logging
import re
import hashlib
import shutil
import requests
from pathlib import Path
from typing import List, Dict, Optional
from fake_useragent import UserAgent
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_cdn_key() -> str:
    """
    自动从 CivitAI 首页获取 CDN key
    如果失败则使用已知的 fallback key
    """
    # 先检查环境变量
    env_key = os.getenv("CIVITAI_CDN_KEY")
    if env_key and env_key.strip():
        logger.info(f"使用环境变量中的 CDN Key")
        return env_key.strip()

    logger.info("尝试自动获取 CDN Key...")
    url = "https://civitai.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        content = response.text

        # 查找 pattern: https://image.civitai.com/{KEY}/
        matches = re.findall(r'https://image\.civitai\.com/([^/]+)/', content)

        if matches:
            key = matches[0]
            logger.info(f"成功获取 CDN Key: {key}")
            return key

        logger.info("未在首页找到 CDN Key pattern")
    except Exception as e:
        logger.warning(f"获取 CDN Key 失败: {e}")

    # Fallback key (已知的可用 key)
    fallback = 'xG1nkqKTMzGDvpLrqFT7WA'
    logger.info(f"使用 fallback CDN Key: {fallback}")
    return fallback


class CivitaiCrawler:

    def __init__(self):
        self.ua = UserAgent()
        self.api_url = "https://search-new.civitai.com/multi-search"
        self.auth_token = f"Bearer 8c46eb2508e21db1e9828a97968d91ab1ca1caa5f70a00e88a2ba1e286603b61"

        # 使用 Session 保持会话
        self.session = requests.Session()

        # 获取 CDN key
        self.cdn_key = get_cdn_key()

        # 从环境变量读取代理配置
        _proxy = os.getenv("PROXY")
        if _proxy:
            _proxy_str = f"http://{_proxy}"
            self.session.proxies = {"http": _proxy_str, "https": _proxy_str}
            self.proxies = {"http": _proxy_str, "https": _proxy_str}
        else:
            self.proxies = None

        self.target_years = [2025]
        self.download_interval = 1  # 下载间隔（秒）,避免请求太快被限制
        self.include_keywords = ["industrial design", "product design", "product rendering","product"]
        self.exclude_keywords = ["anime", "cartoon", "fanart", "nsfw", "portrait",
                                 "character", "woman", "man", "girl", "boy", "person", "human","animal","furry","girl"]
        # 根据目标年份生成目录名（降序排列并用下划线连接）
        years_suffix = "_".join(str(y) for y in sorted(self.target_years, reverse=True))
        self.image_dir = Path(f"./.cache/civitai_com_image_results_{years_suffix}")
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.fail_ids_file = Path("./.cache/fail_ids")
        self.fail_ids_file.parent.mkdir(parents=True, exist_ok=True)

        # 下载缓存目录
        self.cache_dir = Path("./.cache/download_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 进度文件
        self.progress_file = Path("./.cache/crawl_progress.json")
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)

        # CDN key 更新标志（避免频繁更新）
        self.cdn_key_updated = False

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

    def _update_cdn_key(self):
        """更新 CDN key"""
        logger.info("尝试更新 CDN Key...")
        old_key = self.cdn_key
        self.cdn_key = get_cdn_key()
        self.cdn_key_updated = True
        if old_key != self.cdn_key:
            logger.info(f"CDN Key 已更新: {old_key[:10]}... -> {self.cdn_key[:10]}...")
        else:
            logger.info("CDN Key 未发生变化")

    def _save_progress(self, page_count: int, offset: int, total_found: int, total_downloaded: int):
        """保存爬取进度"""
        progress_data = {
            "page_count": page_count,
            "offset": offset,
            "total_found": total_found,
            "total_downloaded": total_downloaded,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"进度已保存: 第{page_count}页, offset={offset}")
        except Exception as e:
            logger.warning(f"保存进度失败: {e}")

    def _load_progress(self) -> dict:
        """读取爬取进度"""
        if not self.progress_file.exists():
            return None
        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            logger.info(f"发现上次的进度: 第{progress.get('page_count')}页, "
                       f"已找到{progress.get('total_found')}条, 已下载{progress.get('total_downloaded')}张")
            logger.info(f"上次爬取时间: {progress.get('timestamp')}")
            return progress
        except Exception as e:
            logger.warning(f"读取进度文件失败: {e}")
            return None

    def _get_headers(self) -> Dict[str, str]:
        return {"user-agent": self.ua.random, "authorization": self.auth_token}

    def _should_include(self, item: Dict) -> bool:
        """检查item是否符合条件"""
        prompt = (item.get("prompt") or "").lower()
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

    def _fetch_page(self, offset: int, limit: int = 51, max_retries: int = 5) -> List[Dict]:
        """
        获取一页数据（支持指数退避重试）
        连接错误时会尝试更新 CDN key
        """
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

        cdn_updated = False  # 标记是否已更新过 CDN key

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url, json=body, headers=self._get_headers(),
                    proxies=self.proxies, timeout=30
                )
                response.raise_for_status()
                hits = response.json().get("results", [{}])[0].get("hits", [])
                return [item for item in hits if self._should_include(item)], hits

            except requests.RequestException as e:
                error_str = str(e)
                _eno = getattr(e, "errno", None)
                is_connection_error = (
                    "ConnectionResetError" in error_str
                    or "Connection aborted" in error_str
                    or "远程主机强迫关闭" in error_str
                    or "Unable to connect to proxy" in error_str
                    or "积极拒绝" in error_str
                    or "408" in error_str
                    or "Request Timeout" in error_str
                    or "Read timed out" in error_str
                    or isinstance(e, requests.exceptions.Timeout)
                    or (_eno is not None and _eno == errno.ECONNRESET)
                )

                # 判断是否需要重试
                if attempt < max_retries - 1:
                    # 如果是连接错误且尚未更新过 CDN key，尝试更新
                    if is_connection_error and not cdn_updated and attempt >= 2:
                        logger.warning(f"检测到连接错误，尝试更新 CDN Key...")
                        self._update_cdn_key()
                        cdn_updated = True

                    # 指数退避: 2^attempt 秒 (1, 2, 4, 8, 16)
                    wait_time = 2 ** attempt
                    logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"请求失败，已重试 {max_retries} 次: {e}")
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

    def _get_download_headers(self) -> Dict[str, str]:
        """获取下载请求头"""
        return {
            "User-Agent": self.ua.random,
            "Authorization": self.auth_token,
            "Referer": "https://civitai.com/",
            "Accept": "image/*"
        }

    def _check_cache(self, url: str) -> Optional[Path]:
        """检查文件是否在缓存中"""
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.cache_dir / cache_key
        if cache_path.exists():
            logger.debug(f"缓存命中: {url}")
            return cache_path
        return None

    def _save_to_cache(self, url: str, source_path: Path):
        """将下载的文件保存到缓存"""
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.cache_dir / cache_key
        try:
            shutil.copy2(source_path, cache_path)
            logger.debug(f"已缓存: {url}")
        except Exception as e:
            logger.warning(f"缓存保存失败: {e}")

    def _download_with_requests(self, url: str, path: Path, max_retries: int = 3) -> bool:
        """
        使用 requests 流式下载图片（参考 CivitAI-Collection-Downloader）
        支持重试机制和缓存
        """
        # 检查缓存
        cached_file = self._check_cache(url)
        if cached_file:
            try:
                shutil.copy2(cached_file, path)
                logger.debug(f"从缓存恢复: {path}")
                return True
            except Exception as e:
                logger.warning(f"从缓存复制失败: {e}")

        headers = self._get_download_headers()

        for attempt in range(max_retries):
            try:
                logger.debug(f"下载尝试 {attempt + 1}/{max_retries}: {url}")

                # 流式下载
                with self.session.get(url, headers=headers, stream=True, timeout=60) as response:
                    response.raise_for_status()

                    # 先写入临时文件
                    temp_path = path.with_suffix('.tmp')
                    with open(temp_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)

                    # 验证文件大小
                    if temp_path.stat().st_size == 0:
                        temp_path.unlink()
                        raise ValueError("下载的文件大小为0")

                    # 重命名为最终文件名
                    temp_path.replace(path)

                    # 保存到缓存
                    self._save_to_cache(url, path)

                    logger.debug(f"下载成功: {path}")
                    return True

            except requests.RequestException as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if hasattr(e, 'response') and e.response is not None:
                    status = e.response.status_code
                    logger.debug(f"HTTP状态码: {status}")
                    if status == 401:
                        logger.error("认证失败 (401)，请检查 auth_token")
                        return False
                    elif status == 404:
                        logger.error("图片不存在 (404)")
                        return False
                    elif status == 429:
                        retry_after = e.response.headers.get('Retry-After')
                        wait_time = int(retry_after) if retry_after else 5
                        logger.info(f"请求频率限制，等待 {wait_time} 秒...")
                        time.sleep(wait_time)
            except Exception as e:
                logger.warning(f"下载失败 (尝试 {attempt + 1}/{max_retries}): {e}")

            # 最后一次尝试不需要等待
            if attempt < max_retries - 1:
                delay = (attempt + 1) * 1  # 递增延迟
                time.sleep(delay)

        logger.error(f"下载失败，已重试 {max_retries} 次: {url}")
        return False

    def _save_json(self, item: Dict, json_path: Path):
        """保存 JSON 元数据"""
        user = item.get("user", {}) or {}
        json_data = {
            "id": item.get("id"),
            "postId": item.get("postId"),
            "prompt": item.get("prompt", ""),
            "type": item.get("type", ""),
            "generationProcess": item.get("generationProcess", ""),
            "createdAt": item.get("createdAt", ""),
            "name": item.get("name", ""),
            "aspectRatio": item.get("aspectRatio", ""),
            "user": {
                "id": user.get("id"),
                "username": user.get("username", "")
            },
            "baseModel": item.get("baseModel", ""),
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

    def _save_item(self, item: Dict) -> bool:
        """
        保存单个item（图片+json）
        使用新的下载方式（参考 CivitAI-Collection-Downloader）
        下载失败时会尝试更新 CDN key 并重试
        """
        url = item.get("url", "")
        item_id = item.get("id")
        created_at = item.get("createdAt", "")
        year = created_at[:4] if created_at else "unknown"

        base_name = os.path.splitext(url.rstrip("/").split("/")[-1])[0]
        ext = os.path.splitext(url.rstrip("/").split("/")[-1])[1] or ".jpg"

        # 文件名格式: {年份}_{id}_{原url值(uuid)}
        filename = f"{year}_{item_id}_{base_name}"
        image_path = self.image_dir / f"{filename}{ext}"
        json_path = self.image_dir / f"{filename}.json"

        # 检查文件是否已存在
        if image_path.exists() and json_path.exists():
            logger.debug(f"文件已存在，跳过: {filename}")
            return False  # 已存在，跳过

        # 如果图片已存在但 JSON 缺失，只更新 JSON
        if image_path.exists() and not json_path.exists():
            logger.info(f"图片已存在，仅更新 JSON: {filename}")
            self._save_json(item, json_path)
            self._remove_fail_id(item_id)
            return True

        # 下载尝试（包括更新 CDN key 后重试）
        download_success = False
        image_url = ""

        for attempt in range(2):  # 最多尝试2次（第一次 + 更新CDN后重试）
            # 构建图片 URL（使用当前 CDN key）
            # 参考: https://image.civitai.com/{cdn_key}/{url}/original=true
            image_url = f"https://image.civitai.com/{self.cdn_key}/{url}/original=true"

            if attempt == 0:
                logger.info(f"正在下载图片: {image_url}")
            else:
                logger.info(f"使用新 CDN Key 重试下载: {filename}")

            logger.debug(f"图片 URL: {image_url}")

            # 使用 requests 流式下载
            if self._download_with_requests(image_url, image_path):
                download_success = True
                break
            else:
                # 第一次下载失败，尝试更新 CDN key
                if attempt == 0:
                    logger.warning(f"下载失败，尝试更新 CDN Key 后重试...")
                    self._update_cdn_key()
                    # 清理可能残留的临时文件
                    if image_path.with_suffix('.tmp').exists():
                        image_path.with_suffix('.tmp').unlink()
                else:
                    # 第二次（更新 CDN 后）仍然失败
                    logger.error(f"更新 CDN Key 后仍然下载失败: ID={item_id}")

        if not download_success:
            self._add_fail_id(item_id)
            logger.error(f"下载失败: ID={item_id}")
            logger.info(f"详情地址: https://civitai.com/images/{item_id}")
            return False

        # 验证图片完整性
        is_valid, error_msg = self._validate_image(image_path)
        if not is_valid:
            # 删除损坏的文件
            if image_path.exists():
                image_path.unlink()
            self._add_fail_id(item_id)
            logger.error(f"校验失败: {error_msg}, ID={item_id}")
            logger.info(f"下载地址: {image_url}")
            logger.info(f"详情地址: https://civitai.com/images/{item_id}")
            return False

        logger.info(f"下载成功: {filename} | https://civitai.com/images/{item_id}")

        # 保存json
        self._save_json(item, json_path)

        # 成功后从失败列表移除
        self._remove_fail_id(item_id)
        return True

    def crawl(self, max_pages: int = None, items_per_page: int = 51, restart: bool = False):
        """
        爬取数据并下载图片

        Args:
            max_pages: 最大爬取页数
            items_per_page: 每页条目数
            restart: 是否重新开始（忽略上次进度）
        """
        logger.info("开始爬取 Civitai 图片...")
        logger.info(f"目标年份: {self.target_years}")
        logger.info(f"关键词: {self.include_keywords}")
        logger.info(f"CDN Key: {self.cdn_key[:10]}...")  # 只显示前10个字符

        # 初始化偏移量和计数
        offset = 0
        page_count = 0
        total_found = 0
        total_downloaded = 0

        # 尝试恢复进度（除非指定 restart）
        if not restart:
            progress = self._load_progress()
            if progress:
                page_count = progress.get("page_count", 0)
                offset = progress.get("offset", 0)
                total_found = progress.get("total_found", 0)
                total_downloaded = progress.get("total_downloaded", 0)
                logger.info(f"从第 {page_count + 1} 页继续爬取...")
        else:
            logger.info("重新开始爬取（忽略上次进度）")
            # 清空进度文件
            if self.progress_file.exists():
                self.progress_file.unlink()

        try:
            while True:
                if max_pages and page_count >= max_pages:
                    logger.info(f"已达到最大页数限制: {max_pages}")
                    break

                logger.info(f"正在获取第 {page_count + 1} 页数据 (offset={offset})...")
                items, hits = self._fetch_page(offset, items_per_page)
                logger.info(f"第 {page_count + 1} 页数据获取完成，原始数据 {len(hits)} 条，符合条件 {len(items)} 条")

                if not hits:
                    logger.info("没有更多数据")
                    break

                page_count += 1

                if not items:
                    logger.info(f"第{page_count}页: 没有符合条件的项目，继续下一页")
                    offset += items_per_page
                    continue
                offset += items_per_page
                total_found += len(items)

                logger.info(f"第{page_count}页: 找到 {len(items)} 条符合条件的")

                # 下载
                downloaded = sum(1 for item in items if self._save_item(item))
                skipped = len(items) - downloaded
                total_downloaded += downloaded

                logger.info(f"第{page_count}页完成: 下载 {downloaded} 张, 跳过 {skipped} 张")

                # 保存进度
                save_page = page_count - 1 if page_count > 0 else 0
                self._save_progress(save_page, offset, total_found, total_downloaded)

                time.sleep(self.download_interval)

            logger.info(f"爬取完成! 共找到 {total_found} 条, 下载 {total_downloaded} 张")

        except KeyboardInterrupt:
            logger.info("\n用户中断爬取，进度已保存")
            logger.info(f"当前进度: 第 {page_count} 页, 已下载 {total_downloaded} 张")
            logger.info("下次运行时会从上次进度继续，如需重新开始请使用 --restart 参数")
            raise

        finally:
            # 爬取完成或中断后，保存最终进度
            self._save_progress(page_count, offset, total_found, total_downloaded)

    def backup_json_files(self):
        """备份现有的 JSON 文件到 .backup 目录"""
        from datetime import datetime

        logger.info("=" * 60)
        logger.info("备份 JSON 文件")
        logger.info("=" * 60)
        logger.info(f"目标目录: {self.image_dir}")

        # 获取所有 JSON 文件
        json_files = list(self.image_dir.glob("*.json"))
        if not json_files:
            logger.info("没有找到 JSON 文件")
            return

        logger.info(f"找到 {len(json_files)} 个 JSON 文件")

        # 用户确认
        confirm = input("\n请输入 'yes' 确认备份: ").strip()
        if confirm.lower() != "yes":
            logger.info("操作已取消")
            return

        # 创建备份目录
        backup_dir = self.image_dir / ".backup" / f"bak_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 复制到备份目录
        for json_file in json_files:
            shutil.copy2(json_file, backup_dir / json_file.name)

        logger.info(f"备份完成: {backup_dir}")
        logger.info(f"已备份 {len(json_files)} 个 JSON 文件")

        # 删除原 JSON 文件
        logger.info("正在删除原 JSON 文件...")
        for json_file in json_files:
            json_file.unlink()

        logger.info(f"已删除 {len(json_files)} 个原 JSON 文件")
        logger.info("下次运行爬虫时会自动补全 JSON 文件")
        logger.info("=" * 60)

    def check_consistency(self):
        """检查图片文件和 JSON 文件的一致性"""
        logger.info("=" * 60)
        logger.info("检查图片和 JSON 一致性")
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

        total_images = len(image_files)
        missing_json = []
        has_json_count = 0

        for image_file in image_files:
            json_file = image_file.with_suffix(".json")
            if json_file.exists():
                has_json_count += 1
            else:
                missing_json.append(image_file.name)

        logger.info("=" * 60)
        logger.info(f"总图片数: {total_images}")
        logger.info(f"有 JSON: {has_json_count}")
        logger.info(f"缺失 JSON: {len(missing_json)}")
        logger.info(f"图片&JSON一致性: {has_json_count}/{total_images} ({has_json_count/total_images*100:.1f}%)")
        logger.info("=" * 60)

        if missing_json:
            logger.info(f"\n缺失 JSON 的图片文件 ({len(missing_json)} 个):")
            for name in missing_json:
                logger.info(f"  - {name}")
                
            if len(missing_json) > 20: # 单独再打印一次方便在底部查看
                logger.info(f"图片&JSON一致性: {has_json_count}/{total_images} ({has_json_count/total_images*100:.1f}%)")
        else:
            logger.info("\n✓ 所有图片都有对应的 JSON 文件")
        logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Civitai图片爬虫")
    parser.add_argument("--max-pages", type=int, default=None, help="最大爬取页数")
    parser.add_argument("--restart", action="store_true", help="重新开始爬取（忽略上次进度）")
    parser.add_argument("--backup-json", action="store_true", help="备份现有 JSON 文件")
    parser.add_argument("--check", action="store_true", help="检查图片和 JSON 一致性")
    args = parser.parse_args()

    crawler = CivitaiCrawler()

    if args.backup_json:
        crawler.backup_json_files()
    elif args.check:
        crawler.check_consistency()
    else:
        crawler.crawl(max_pages=args.max_pages, restart=args.restart)
