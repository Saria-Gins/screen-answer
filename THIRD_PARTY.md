# 第三方组件

本项目以 MIT 许可发布，运行时依赖以下第三方组件（各自遵循其原许可）：

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| [PySide6 / Qt 6](https://www.qt.io/) | 图形界面（Qt for Python） | LGPL-3.0（动态链接；如需静态链接请遵守 Qt 商业/开源条款） |
| [mss](https://github.com/BoboTiG/python-mss) | 屏幕截取 | MIT |
| [Pillow](https://python-pillow.org/) | 图像处理 | MIT-CMU |
| [requests](https://requests.readthedocs.io/) | HTTP 客户端 | Apache-2.0 |
| [pypdf](https://github.com/py-pdf/pypdf) | PDF 文本抽取 | BSD-3-Clause |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | PDF 渲染（扫描件 OCR 前置） | Apache-2.0 / BSD-3-Clause（PDFium） |
| [winrt-* (Windows SDK projections)](https://pypi.org/project/winrt-runtime/) | 调用 Windows OCR | MIT |

可选：Windows 系统自带的 OCR 语言包（中文需在「设置 → 时间和语言 → 语言」中安装“光学字符识别”功能）。

打包分发时请保留本文件和各自许可声明。
