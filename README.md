# 杂志图书馆 (Magazine Library)

一个简单的在线杂志管理系统，支持PDF和EPUB格式的杂志上传、分类和管理。

## 功能特点

- 支持PDF和EPUB格式杂志上传
- 杂志分类管理
- 按分类和格式筛选
- 简洁美观的界面设计

## 技术栈

- 前端：HTML, CSS, JavaScript
- 后端：Python (Flask)
- 数据存储：SQLite

## 项目结构

```
Magazine Library/
├── static/
│   ├── css/
│   ├── js/
│   └── uploads/
├── templates/
├── app.py
├── requirements.txt
└── README.md
```

## 环境配置
1. 创建并激活虚拟环境（推荐）
bash
python -m venv venv
source venv/bin/activate # Linux/Mac
venv\Scripts\activate # Windows
## 安装说明

1. 安装Python依赖：
```bash
pip install -r requirements.txt
```

2. 运行应用：
```bash
python app.py
```

3. 在浏览器中访问：http://localhost:5000 
