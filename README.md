# Civitai 图片爬虫

专门用于从 Civitai 抓取产品设计和工业设计相关图片的 Python 爬虫工具。

## 功能特点

- 支持按关键词过滤（包含/排除关键词）
- 支持按年份过滤（默认 2025 年）
- 数据持久化存储（SQLite）
- 支持三种运行模式：
  - 仅爬取数据（不下载图片）
  - 仅下载图片（不爬取新数据）
  - 边爬取边下载
- 自动跳过已下载的图片
- 随机 User-Agent 避免 IP 封禁
- 支持代理配置

## 环境要求

- **Python 3.12**

## 安装

1. 克隆或下载本项目

2. 安装依赖：

```bash
pip install -r requirements.txt
```

## 使用方法

### 仅爬取数据，不下载图片 [推荐,可后续新开窗口下载图片]

```bash
python civitai_crawler.py --crawl-only
```

### 仅下载图片，不爬取新数据

```bash
python civitai_crawler.py --download-only
```

### 限制爬取页数

```bash
python civitai_crawler.py --crawl-only --max-pages 10
```

### 边爬取边下载

```bash
python civitai_crawler.py
```

## 项目结构

```
.
├── civitai_crawler.py    # 爬虫主程序
├── requirements.txt       # 依赖列表
├── .gitignore            # Git 忽略配置
└── .cache/               # 缓存目录（自动创建）
    ├── civitai_images.db  # SQLite 数据库
    └── civitai_com_image_results/  # 下载的图片
```

## 配置说明

在 [civitai_crawler.py](civitai_crawler.py) 中可以修改以下配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `include_keywords` | 必须包含的关键词 | `["industrial design", "product design", "product rendering"]` |
| `exclude_keywords` | 排除的关键词 | `["anime", "cartoon", "nsfw", ...]` |
| `target_year` | 目标年份 | `2025` |
| `proxy` | 代理地址 | `"http://127.0.0.1:7890"` |

## 注意事项

1. 请确保遵守 Civitai 的使用条款和服务协议
2. 建议配置代理以避免 IP 限制
3. 图片默认保存在 `.cache/civitai_com_image_results/` 目录
4. 已下载的图片会自动跳过，不会重复下载

## 依赖项

- `requests` - HTTP 请求库
