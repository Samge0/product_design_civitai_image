# Civitai 图片爬虫

专门用于从 Civitai 抓取产品设计和工业设计相关图片的 Python 爬虫工具。

## 功能特点

- 支持按关键词过滤（包含/排除关键词）
- 支持按年份过滤（默认 2025 年）
- **智能进度管理**：自动保存爬取进度，支持断点续传
- **自动重试机制**：请求超时自动指数退避重试
- **流式下载**：使用 requests 流式下载，支持缓存
- **动态 CDN Key**：自动获取最新 CDN key，确保下载稳定
- 自动跳过已下载的图片
- 随机 User-Agent 避免 IP 封禁
- 支持代理配置

## 环境要求

- **Python 3.8+**

## 安装

1. 克隆或下载本项目

2. 安装依赖：

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本使用（自动断点续传）

```bash
python civitai_crawler.py
```

### 限制爬取页数

```bash
python civitai_crawler.py --max-pages 10
```

### 重新开始（忽略上次进度）

```bash
python civitai_crawler.py --restart
```

### 组合使用

```bash
# 重新开始并限制页数
python civitai_crawler.py --restart --max-pages 5
```

### 检查图片和 JSON 一致性

```bash
python civitai_crawler.py --check
```

查看缺失 JSON 的图片文件，方便判断是否需要补全数据。

### 备份并更新 JSON 文件

当 JSON 格式更新时，可以备份旧 JSON 并让爬虫自动补全新格式：

```bash
# 1. 检查一致性
python civitai_crawler.py --check

# 2. 备份现有 JSON 文件（备份后自动删除原 JSON）
python civitai_crawler.py --backup-json

# 3. 重新运行爬虫，自动为已下载的图片补全新格式的 JSON
python civitai_crawler.py
```

### 中断恢复

- 按 `Ctrl+C` 中断爬取，进度会自动保存
- 下次运行会从上次位置继续
- JSON 文件会自动补全：图片已存在但 JSON 缺失时，仅更新 JSON

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--max-pages N` | 最大爬取页数 |
| `--restart` | 重新开始（忽略上次进度） |
| `--check` | 检查图片和 JSON 一致性 |
| `--backup-json` | 备份现有 JSON 文件并删除原文件 |

## 项目结构

```
.
├── civitai_crawler.py    # 爬虫主程序
├── requirements.txt       # 依赖列表
├── .gitignore            # Git 忽略配置
└── .cache/               # 缓存目录（自动创建）
    ├── crawl_progress.json  # 爬取进度文件
    ├── fail_ids            # 失败记录
    ├── download_cache/      # 下载缓存
    └── civitai_com_image_results_2025/  # 下载的图片
        └── .backup/         # JSON 备份目录
            └── bak_YYYYMMDDHHMMSS/  # 按时间戳命名的备份
```

## 配置说明

在 [civitai_crawler.py](civitai_crawler.py) 中可以修改以下配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `include_keywords` | 必须包含的关键词 | `["industrial design", "product design", "product rendering"]` |
| `exclude_keywords` | 排除的关键词 | `["anime", "cartoon", "nsfw", ...]` |
| `target_years` | 目标年份 | `[2025]` |
| `download_interval` | 下载间隔（秒） | `1` |

### 环境变量配置

创建 `.env` 文件配置以下选项：

```bash
# 代理配置（可选）
PROXY=127.0.0.1:7890

# CDN Key（可选，不填则自动获取）
CIVITAI_CDN_KEY=your_key_here
```

## 注意事项

1. 请确保遵守 Civitai 的使用条款和服务协议
2. 建议配置代理以避免 IP 限制
3. 图片默认保存在 `.cache/civitai_com_image_results_2025/` 目录
4. 文件名格式：`{年份}_{id}_{uuid}.jpg`
5. 已下载的图片会自动跳过，不会重复下载
6. 请求失败会自动重试（最多 5 次，指数退避）
7. **JSON 自动补全**：图片已存在但 JSON 缺失时，仅更新 JSON，不重新下载图片

## JSON 文件说明

每张图片都配有同名的 `.json` 文件，包含以下元数据：

| 字段 | 说明 |
|------|------|
| `id` | 图片 ID |
| `prompt` | 提示词 |
| `type` | 类型（如 "image"） |
| `generationProcess` | 生成过程（如 "txt2img"） |
| `createdAt` | 创建时间 |
| `name` | 原始文件名 |
| `aspectRatio` | 宽高比 |
| `user.id` | 用户 ID |
| `user.username` | 用户名 |
| `baseModel` | 基础模型 |

## 依赖项

- `requests` - HTTP 请求库
- `Pillow` - 图片验证
- `fake-useragent` - 随机 User-Agent


### 修复缺失的 JSON 文件 (备选方案)

使用 `fix-json.py` 脚本可以单独修复缺失 JSON 的图片文件：

```bash
# 修复所有缺失的 JSON 文件
python fix-json.py

# 修复前 10 个文件
python fix-json.py --limit 10

# 从第 50 个文件开始修复（断点续传）
python fix-json.py --start 50

# 组合使用：从第 50 个开始，修复 20 个
python fix-json.py --start 50 --limit 20
```

**修复原理：**

1. 从图片文件名中提取 Civitai 图片 ID（格式：`{年份}_{id}_{uuid}.jpg`）
2. 请求 `https://civitai.com/images/{id}` 获取页面 HTML
3. 从 `<script id="__NEXT_DATA__">` 标签中提取页面数据
4. 使用 postId 请求 API `https://civitai.com/api/v1/images?limit=1&postId={postId}` 获取完整数据
5. 合并两个数据源，生成 JSON 文件

**数据源映射：**

| JSON 字段 | 数据来源 |
|-----------|----------|
| `id` | 页面数据 |
| `postId` | 页面数据 |
| `prompt` | API 数据 (`meta.prompt`) |
| `type` | 页面数据 |
| `generationProcess` | API 数据 (`meta.workflow`) |
| `createdAt` | 页面数据 |
| `name` | 页面数据 |
| `aspectRatio` | 根据宽高计算 (Landscape/Portrait/Square) |
| `user.id` | 页面数据 |
| `user.username` | 页面数据 |
| `baseModel` | API 数据 |

**已知问题：**

- `generationProcess` 字段无法从 API 数据中获取（`meta.workflow` 返回空值），该字段在生成的 JSON 中将为空字符串