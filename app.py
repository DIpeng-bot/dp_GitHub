from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
import os
import sqlite3
from datetime import datetime
import fitz  # PyMuPDF
from PIL import Image
import io
import ebooklib
from ebooklib import epub
import base64
import re
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# 配置上传文件夹
UPLOAD_FOLDER = 'static/uploads'
COVERS_FOLDER = 'static/covers'
ALLOWED_EXTENSIONS = {'pdf', 'epub'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['COVERS_FOLDER'] = COVERS_FOLDER

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(COVERS_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    # 检查表是否存在
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='magazines'")
    table_exists = c.fetchone() is not None
    
    if not table_exists:
        # 创建新表
        c.execute('''
            CREATE TABLE magazines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                category TEXT NOT NULL,
                format TEXT NOT NULL,
                upload_date DATETIME NOT NULL,
                cover_image_original TEXT,
                cover_image_thumbnail TEXT
            )
        ''')
    else:
        # 检查是否需要更新表结构
        c.execute("PRAGMA table_info(magazines)")
        columns = [column[1] for column in c.fetchall()]
        
        # 如果需要添加新列
        if 'cover_image_original' not in columns:
            c.execute('ALTER TABLE magazines ADD COLUMN cover_image_original TEXT')
        if 'cover_image_thumbnail' not in columns:
            c.execute('ALTER TABLE magazines ADD COLUMN cover_image_thumbnail TEXT')
        
        # 如果存在旧的cover_image列，迁移数据
        if 'cover_image' in columns:
            c.execute('UPDATE magazines SET cover_image_thumbnail = cover_image WHERE cover_image IS NOT NULL')
            # SQLite不支持直接删除列，所以我们需要创建新表并迁移数据
            c.execute('''
                CREATE TABLE magazines_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    category TEXT NOT NULL,
                    format TEXT NOT NULL,
                    upload_date DATETIME NOT NULL,
                    cover_image_original TEXT,
                    cover_image_thumbnail TEXT
                )
            ''')
            c.execute('''
                INSERT INTO magazines_new 
                (id, title, filename, category, format, upload_date, cover_image_thumbnail)
                SELECT id, title, filename, category, format, upload_date, cover_image_thumbnail
                FROM magazines
            ''')
            c.execute('DROP TABLE magazines')
            c.execute('ALTER TABLE magazines_new RENAME TO magazines')
    
    conn.commit()
    conn.close()

def extract_cover_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]  # 获取第一页
        
        # 首先尝试获取页面中的图片
        image_list = page.get_images()
        
        if image_list:  # 如果找到了图片
            # 获取第一张图片
            img_info = image_list[0]
            base_image = doc.extract_image(img_info[0])
            image_bytes = base_image["image"]
            
            # 转换为PIL图像
            original_img = Image.open(io.BytesIO(image_bytes))
            
            # 如果图片是RGBA模式，转换为RGB
            if original_img.mode == 'RGBA':
                original_img = original_img.convert('RGB')
                
        else:  # 如果没有找到图片，则渲染整个页面
            # 使用更高的分辨率渲染页面
            zoom = 4
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # 转换为PIL图像
            img_data = pix.tobytes()
            original_img = Image.frombytes("RGB", [pix.width, pix.height], img_data)
        
        # 创建缩略图
        thumbnail_img = original_img.copy()
        thumbnail_img.thumbnail((300, 400), Image.Resampling.LANCZOS)
        
        # 保存原图和缩略图
        original_byte_arr = io.BytesIO()
        thumbnail_byte_arr = io.BytesIO()
        
        original_img.save(original_byte_arr, format='JPEG', quality=95)
        thumbnail_img.save(thumbnail_byte_arr, format='JPEG', quality=85)
        
        doc.close()
        return original_byte_arr.getvalue(), thumbnail_byte_arr.getvalue()
        
    except Exception as e:
        print(f"PDF封面提取错误: {e}")
        return None, None

def extract_cover_from_epub(epub_path):
    try:
        book = epub.read_epub(epub_path)
        
        # 尝试从元数据中获取封面
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_COVER or \
               item.get_type() == ebooklib.ITEM_IMAGE:
                img_data = item.get_content()
                img = Image.open(io.BytesIO(img_data))
                
                # 调整图片大小
                img.thumbnail((300, 400), Image.Resampling.LANCZOS)
                
                # 保存为JPEG
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=85)
                img_byte_arr = img_byte_arr.getvalue()
                
                return img_byte_arr
        
        return None
    except Exception as e:
        print(f"EPUB封面提取错误: {e}")
        return None

def save_cover_image(original_data, thumbnail_data, filename):
    if original_data and thumbnail_data:
        # 保存原图
        original_filename = f"original_cover_{filename}.jpg"
        original_path = os.path.join(app.config['COVERS_FOLDER'], original_filename)
        with open(original_path, 'wb') as f:
            f.write(original_data)
            
        # 保存缩略图
        thumbnail_filename = f"thumbnail_cover_{filename}.jpg"
        thumbnail_path = os.path.join(app.config['COVERS_FOLDER'], thumbnail_filename)
        with open(thumbnail_path, 'wb') as f:
            f.write(thumbnail_data)
            
        return original_filename, thumbnail_filename
    return None, None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    c.execute('SELECT * FROM magazines ORDER BY upload_date DESC')
    magazines = c.fetchall()
    c.execute('SELECT DISTINCT category FROM magazines')
    categories = [row[0] for row in c.fetchall()]
    conn.close()
    return render_template('index.html', 
                         magazines=magazines, 
                         categories=categories,
                         current_category='all',
                         current_format='all')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('没有选择文件')
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash('没有选择文件')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_format = filename.rsplit('.', 1)[1].lower()
        title = request.form.get('title', filename)
        category = request.form.get('category', '未分类')
        
        # 保存文件
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # 提取并保存封面
        if file_format == 'pdf':
            original_data, thumbnail_data = extract_cover_from_pdf(file_path)
            original_filename, thumbnail_filename = save_cover_image(original_data, thumbnail_data, filename)
        else:  # epub
            cover_data = extract_cover_from_epub(file_path)
            if cover_data:
                # 为EPUB创建缩略图
                img = Image.open(io.BytesIO(cover_data))
                
                # 保存原图
                original_byte_arr = io.BytesIO()
                img.save(original_byte_arr, format='JPEG', quality=95)
                original_data = original_byte_arr.getvalue()
                
                # 创建并保存缩略图
                thumbnail_img = img.copy()
                thumbnail_img.thumbnail((300, 400), Image.Resampling.LANCZOS)
                thumbnail_byte_arr = io.BytesIO()
                thumbnail_img.save(thumbnail_byte_arr, format='JPEG', quality=85)
                thumbnail_data = thumbnail_byte_arr.getvalue()
                
                original_filename, thumbnail_filename = save_cover_image(original_data, thumbnail_data, filename)
            else:
                original_filename = thumbnail_filename = None
        
        # 保存到数据库
        conn = sqlite3.connect('magazines.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO magazines (title, filename, category, format, upload_date, cover_image_original, cover_image_thumbnail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, filename, category, file_format, datetime.now(), original_filename, thumbnail_filename))
        conn.commit()
        conn.close()
        
        flash('文件上传成功！')
        return redirect(url_for('index'))
    
    flash('不支持的文件格式')
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_magazine(id):
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    # 获取文件名和封面图片名
    c.execute('SELECT filename, cover_image_original, cover_image_thumbnail FROM magazines WHERE id = ?', (id,))
    result = c.fetchone()
    
    if result:
        filename, original_cover, thumbnail_cover = result
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        original_cover_path = os.path.join(app.config['COVERS_FOLDER'], original_cover) if original_cover else None
        thumbnail_cover_path = os.path.join(app.config['COVERS_FOLDER'], thumbnail_cover) if thumbnail_cover else None
        
        # 从数据库中删除记录
        c.execute('DELETE FROM magazines WHERE id = ?', (id,))
        conn.commit()
        
        # 删除文件
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # 删除封面图片
        if original_cover_path and os.path.exists(original_cover_path):
            os.remove(original_cover_path)
        if thumbnail_cover_path and os.path.exists(thumbnail_cover_path):
            os.remove(thumbnail_cover_path)
            
        flash('杂志已成功删除！')
    else:
        flash('未找到杂志！')
    
    conn.close()
    return redirect(url_for('index'))

@app.route('/download/<int:id>')
def download_magazine(id):
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    c.execute('SELECT filename, title FROM magazines WHERE id = ?', (id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        filename = result[0]
        title = result[1]
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            filename,
            as_attachment=True,
            download_name=f"{title}.{filename.split('.')[-1]}"
        )
    
    flash('未找到该杂志！')
    return redirect(url_for('index'))

@app.route('/filter')
def filter_magazines():
    category = request.args.get('category', 'all')
    file_format = request.args.get('format', 'all')
    
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    query = 'SELECT * FROM magazines WHERE 1=1'
    params = []
    
    if category and category != 'all':
        query += ' AND category = ?'
        params.append(category)
    
    if file_format and file_format != 'all':
        query += ' AND format = ?'
        params.append(file_format)
    
    query += ' ORDER BY upload_date DESC'
    
    c.execute(query, params)
    magazines = c.fetchall()
    c.execute('SELECT DISTINCT category FROM magazines')
    categories = [row[0] for row in c.fetchall()]
    conn.close()
    
    return render_template('index.html', 
                         magazines=magazines, 
                         categories=categories,
                         current_category=category,
                         current_format=file_format)

if __name__ == '__main__':
    init_db()
    app.run(debug=True) 